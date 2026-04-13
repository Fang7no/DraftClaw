import json
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import PropertyMock, patch

import fitz


REPO_ROOT = Path(__file__).resolve().parents[1]
DRAFTCLAW_ROOT = REPO_ROOT / "draftclaw"
if str(DRAFTCLAW_ROOT) not in sys.path:
    sys.path.insert(0, str(DRAFTCLAW_ROOT))

import prompt_loader  # noqa: E402
import main as draft_main  # noqa: E402
import logger as draft_logger  # noqa: E402
from bbox_locator import BBoxLocator  # noqa: E402
from chunker import ChunkSplitter  # noqa: E402
from agents.plan_agent import PlanAgent  # noqa: E402
from agents.recheck_agent import RecheckAgent, TextRecheckAgent  # noqa: E402
from agents.summary_agent import SummaryAgent  # noqa: E402
from agents.vision_agent import VisionValidationAgent  # noqa: E402
from agents import llm_utils  # noqa: E402
from agents.llm_utils import ChatCompletionClient, LLMCallResult, build_multimodal_user_content  # noqa: E402
from agents.explore_agent import ExploreAgent  # noqa: E402
import config_validator  # noqa: E402
from issue_review import get_issue_review_decision  # noqa: E402
from pdf_annotation_exporter import export_annotated_pdf_bytes  # noqa: E402
from report_export_renderer import render_export_report_html  # noqa: E402
from pdf_screenshot import PDFIssueScreenshotRenderer  # noqa: E402
from web.tasks import Task, TaskManager  # noqa: E402


class PromptWorkflowTests(unittest.TestCase):
    @staticmethod
    def _sample_bbox_locator():
        return BBoxLocator(
            {
                "content_list_v2": [
                    [
                        {
                            "type": "paragraph",
                            "bbox": [100, 120, 400, 220],
                            "content": {"text": "Alpha beta. Gamma delta."},
                        }
                    ]
                ]
            }
        )

    def test_prompt_sections_load_from_real_files(self):
        system_text = prompt_loader.load_prompt_section_text("plan_prompt.md", "system")
        user_text = prompt_loader.load_prompt_section_text("plan_prompt.md", "user")

        self.assertIn("## Role", system_text)
        self.assertIn("## Task", system_text)
        self.assertIn("## Rules", system_text)
        self.assertIn("section_role", user_text)
        self.assertIn("visual_element_role", user_text)

    def test_split_stage_prompts_load_from_nested_paths(self):
        explore_system = prompt_loader.load_prompt_section_text(
            "explore/local_initial_prompt.md",
            "system",
        )
        search_user = prompt_loader.load_prompt_section_text(
            "search/intent_prompt.md",
            "user",
        )

        self.assertIn("## Role", explore_system)
        self.assertIn("local_error_list", explore_system)
        self.assertIn("不要关注图片视觉内容", explore_system)
        self.assertNotIn("Multimodal Inconsistency", explore_system)
        self.assertIn("固定 6 类", explore_system)
        self.assertNotIn("固定 8 类", explore_system)
        self.assertNotIn("固定 9 类", explore_system)
        self.assertNotIn("9. `Multimodal Inconsistency`", explore_system)
        self.assertIn("search_queries", search_user)

    def test_explore_system_prompts_render_current_date(self):
        agent = ExploreAgent()

        with patch.object(ExploreAgent, "_current_date_text", return_value="2026-04-10"):
            global_initial = agent._render_system_prompt("global_initial")
            local_finalize = agent._render_system_prompt("local_finalize")

        self.assertIn("当前日期: 2026-04-10", global_initial)
        self.assertIn("当前日期: 2026-04-10", local_finalize)
        self.assertNotIn("{{ current_date_text }}", global_initial)
        self.assertNotIn("{{ current_date_text }}", local_finalize)

    def test_global_initial_prompt_only_uses_marked_document_context(self):
        rendered = prompt_loader.render_prompt_section_template(
            "explore/global_initial_prompt.md",
            "user",
            document_overview="<current chunk>\n[P001-I0000] Alpha beta.\n</current chunk>",
        )

        self.assertIn("已标记的 PDF 全文上下文", rendered)
        self.assertIn("<current chunk>", rendered)
        self.assertNotIn("{{chunk_content}}", rendered)
        self.assertNotIn("{{neighbor_context}}", rendered)
        self.assertNotIn("{{global_chunk_map}}", rendered)
        self.assertNotIn("{{plan_markdown}}", rendered)
        self.assertNotIn("{{local_error_list_json}}", rendered)

    def test_document_overview_is_clean_full_markdown_without_heading_summary(self):
        overview = draft_main.build_document_overview(
            "# Intro\nAlpha beta.\n![](images/figure.jpg)\nFig. 1. Caption.\n# Method\nGamma delta."
        )

        self.assertNotIn("Headings:", overview)
        self.assertNotIn("Full PDF Markdown:", overview)
        self.assertNotIn("images/figure.jpg", overview)
        self.assertEqual(overview.count("# Intro"), 1)
        self.assertEqual(overview.count("# Method"), 1)
        self.assertIn("Fig. 1. Caption.", overview)

    def test_review_excerpt_strips_image_urls_but_keeps_caption_text(self):
        bundle = draft_main.build_review_excerpt_bundle(
            "Intro text.\n\n![](images/figure.jpg)\n"
            "Fig. 1. Important caption with inline image ![](images/inline.jpg).\n\n"
            "Conclusion text."
        )

        self.assertNotIn("![](images/figure.jpg)", bundle["text"])
        self.assertNotIn("images/figure.jpg", bundle["text"])
        self.assertNotIn("images/inline.jpg", bundle["text"])
        self.assertIn("Fig. 1. Important caption with inline image .", bundle["text"])
        self.assertEqual(bundle["audit"]["removed_image_markdown_lines"], 2)
        self.assertFalse(bundle["audit"]["image_markdown_placeholders_sent_to_llm"])

    def test_review_excerpt_uses_cleaned_full_chunk_without_truncation(self):
        bundle = draft_main.build_review_excerpt_bundle(
            "Start text.\n"
            "Middle ordinary sentence that should not need a keyword to be retained.\n"
            "![](images/figure.jpg)\n"
            "Fig. 2. Caption text.\n"
            "Final sentence.",
            max_chars=20,
        )

        self.assertIn("Start text.", bundle["text"])
        self.assertIn("Middle ordinary sentence", bundle["text"])
        self.assertIn("Fig. 2. Caption text.", bundle["text"])
        self.assertIn("Final sentence.", bundle["text"])
        self.assertNotIn("images/figure.jpg", bundle["text"])
        self.assertEqual(bundle["audit"]["input_strategy"], "cleaned_full_chunk")

    def test_prepare_chunk_review_input_does_not_collect_images_for_text_agents(self):
        class DummyLogger:
            def log(self, *args, **kwargs):
                return None

            def progress(self, *args, **kwargs):
                return None

        chunk = draft_main.Chunk(
            id=0,
            content="Intro.\n![](images/figure.jpg)\nFig. 1. Caption.",
            char_count=44,
            start_pos=0,
            end_pos=44,
        )

        prepared = draft_main.prepare_chunk_review_input(
            index=0,
            chunk=chunk,
            chunks=[chunk],
            document_overview="Intro.\n![](images/figure.jpg)\nFig. 1. Caption.",
            document_images=[
                {
                    "img_path": "images/figure.jpg",
                    "local_path": r"C:\tmp\figure.jpg",
                    "image_caption": ["Fig. 1. Caption."],
                }
            ],
            cache_dir=Path("."),
            logger=DummyLogger(),
        )

        self.assertEqual(prepared["chunk_images"], [])
        self.assertNotIn("images/figure.jpg", prepared["review_excerpt"])
        self.assertFalse(prepared["review_audit"]["image_binary_sent_to_llm"])
        self.assertEqual(prepared["review_audit"]["llm_input_mode"], "text-only")

    def test_chunk_splitter_keeps_full_paragraphs_instead_of_cutting_at_sentence_boundaries(self):
        paragraph_one = "Sentence one. Sentence two. Sentence three."
        paragraph_two = "Second paragraph stays complete."
        text = f"{paragraph_one}\n\n{paragraph_two}"

        chunks = ChunkSplitter(min_size=10, max_size=30).split(text)

        self.assertEqual(len(chunks), 2)
        self.assertEqual(chunks[0].content, paragraph_one)
        self.assertEqual(chunks[1].content, paragraph_two)
        self.assertGreater(chunks[0].char_count, 30)

    def test_chunk_splitter_keeps_single_oversized_paragraph_intact(self):
        paragraph_one = "A" * 80
        paragraph_two = "B" * 20
        text = f"{paragraph_one}\n\n{paragraph_two}"

        chunks = ChunkSplitter(min_size=10, max_size=40).split(text)

        self.assertEqual(len(chunks), 2)
        self.assertEqual(chunks[0].content, paragraph_one)
        self.assertEqual(chunks[1].content, paragraph_two)
        self.assertGreater(chunks[0].char_count, 40)

    def test_build_local_chunk_records_splits_one_global_chunk_into_smaller_local_parts(self):
        text = "\n\n".join(
            [
                "A" * 2200,
                "B" * 2200,
                "C" * 2200,
                "D" * 2200,
            ]
        )
        chunk = draft_main.Chunk(
            id=0,
            content=text,
            char_count=len(text),
            start_pos=0,
            end_pos=len(text),
        )

        records = draft_main.build_local_chunk_records(chunk)

        self.assertEqual(len(records), 2)
        self.assertEqual(records[0]["local_chunk_id"], 0)
        self.assertEqual(records[1]["local_chunk_id"], 1)
        self.assertIn("A" * 20, records[0]["review_excerpt"])
        self.assertIn("C" * 20, records[1]["review_excerpt"])

    def test_build_local_chunk_records_keep_full_paragraphs(self):
        paragraph_one = "Sentence one. Sentence two. Sentence three."
        paragraph_two = "Second paragraph stays complete."
        chunk_text = f"{paragraph_one}\n\n{paragraph_two}"
        chunk = draft_main.Chunk(
            id=0,
            content=chunk_text,
            char_count=len(chunk_text),
            start_pos=0,
            end_pos=len(chunk_text),
        )

        with patch.object(draft_main, "LOCAL_CHUNK_MIN_SIZE", 10), patch.object(
            draft_main,
            "LOCAL_CHUNK_MAX_SIZE",
            30,
        ):
            records = draft_main.build_local_chunk_records(chunk)

        self.assertEqual(len(records), 2)
        self.assertEqual(records[0]["current_chunk_text"], paragraph_one)
        self.assertEqual(records[1]["current_chunk_text"], paragraph_two)
        self.assertEqual(records[0]["review_excerpt"], paragraph_one)
        self.assertEqual(records[1]["review_excerpt"], paragraph_two)

    def test_cached_non_mineru_parse_refreshes(self):
        class CachedParse:
            parser_backend = "legacy_non_mineru"

        self.assertTrue(draft_main.needs_parser_backend_refresh(CachedParse()))

    def test_cached_mineru_parse_does_not_refresh(self):
        class CachedParse:
            parser_backend = "mineru"

        self.assertFalse(draft_main.needs_parser_backend_refresh(CachedParse()))

    def test_document_overview_marks_current_chunk_inline(self):
        overview = (
            "Headings:\n# Intro\n\nFull PDF Markdown:\n"
            "# Intro\nAlpha beta.\nGamma delta.\nConclusion."
        )

        marked = draft_main.mark_current_chunk_in_document_overview(
            overview,
            "Alpha beta.\nGamma delta.",
        )

        self.assertIn("<current chunk>\nAlpha beta.\nGamma delta.\n</current chunk>", marked)
        self.assertEqual(marked.count("<current chunk>"), 1)
        self.assertEqual(marked.count("</current chunk>"), 1)
        self.assertNotIn("### 当前 Chunk", marked)

    def test_explore_agent_rejects_multimodal_issue_type(self):
        agent = ExploreAgent()

        result = agent._post_process_issues(
            [
                {
                    "type": "Multimodal Inconsistency",
                    "severity": "high",
                    "description": "Image and caption appear inconsistent.",
                    "evidence": ["P001-I0000"],
                    "location": "P001-I0000",
                    "reasoning": "This requires image inspection.",
                }
            ],
            default_stage="local",
        )

        self.assertEqual(result, [])

    def test_duplicate_prompt_sections_raise_error(self):
        original_dir = prompt_loader.PROMPTS_DIR
        with tempfile.TemporaryDirectory() as temp_dir:
            temp_path = Path(temp_dir)
            (temp_path / "duplicate_prompt.md").write_text(
                "[SYSTEM]\nfirst\n[SYSTEM]\nsecond\n",
                encoding="utf-8",
            )
            prompt_loader.PROMPTS_DIR = temp_path
            try:
                with self.assertRaises(ValueError):
                    prompt_loader.parse_prompt_sections("duplicate_prompt.md")
            finally:
                prompt_loader.PROMPTS_DIR = original_dir

    def test_prompt_template_supports_spaced_placeholders(self):
        original_dir = prompt_loader.PROMPTS_DIR
        with tempfile.TemporaryDirectory() as temp_dir:
            temp_path = Path(temp_dir)
            (temp_path / "spaced_prompt.md").write_text(
                "[USER]\n当前日期: {{ current_date_text }}\nChunk: {{chunk_content}}\n",
                encoding="utf-8",
            )
            prompt_loader.PROMPTS_DIR = temp_path
            try:
                rendered = prompt_loader.render_prompt_section_template(
                    "spaced_prompt.md",
                    "user",
                    current_date_text="2026-04-10",
                    chunk_content="Alpha",
                )
            finally:
                prompt_loader.PROMPTS_DIR = original_dir

        self.assertIn("当前日期: 2026-04-10", rendered)
        self.assertIn("Chunk: Alpha", rendered)

    def test_prompt_template_preserves_backslashes_in_values(self):
        original_dir = prompt_loader.PROMPTS_DIR
        with tempfile.TemporaryDirectory() as temp_dir:
            temp_path = Path(temp_dir)
            (temp_path / "backslash_prompt.md").write_text(
                "[USER]\n{{ chunk_content }}\n",
                encoding="utf-8",
            )
            prompt_loader.PROMPTS_DIR = temp_path
            try:
                rendered = prompt_loader.render_prompt_section_template(
                    "backslash_prompt.md",
                    "user",
                    chunk_content=r"bad \lambda and 50 \% should stay literal",
                )
            finally:
                prompt_loader.PROMPTS_DIR = original_dir

        self.assertEqual(rendered, r"bad \lambda and 50 \% should stay literal")

    def test_plan_agent_normalizes_structured_fields(self):
        result = PlanAgent._normalize_result(
            {
                "section_role": "",
                "chunk_purpose": "Explain the method core.",
                "core_content": "",
                "visual_element_role": "",
                "query_list": "Check logic",
            }
        )

        self.assertIn("section_role", result)
        self.assertIn("chunk_purpose", result)
        self.assertIn("core_content", result)
        self.assertIn("visual_element_role", result)
        self.assertEqual(result["query_list"], ["Check logic"])

    def test_summary_agent_rehydrates_candidate_metadata(self):
        agent = SummaryAgent()
        normalized = [
            {
                "type": "Method Logic",
                "severity": "medium",
                "description": "Method step order is inconsistent.",
                "evidence": ["Original evidence"],
                "location": "Original location.",
                "reasoning": "Reasoning.",
                "source_stage": "local",
            }
        ]
        candidates = [
            {
                "type": "Method Logic",
                "severity": "medium",
                "description": "Method step order is inconsistent.",
                "evidence": ["Original evidence"],
                "location": "Original location.",
                "reasoning": "Reasoning.",
                "source_stage": "local",
                "search_result": {"search_performed": True},
                "vision_validation": {"decision": "keep"},
                "bbox_lookup_resolved": True,
            }
        ]

        hydrated = agent._rehydrate_issues(normalized, candidates)

        self.assertEqual(hydrated[0]["search_result"], {"search_performed": True})
        self.assertEqual(hydrated[0]["vision_validation"], {"decision": "keep"})
        self.assertTrue(hydrated[0]["bbox_lookup_resolved"])

    def test_bbox_locator_resolves_anchor_ids_and_builds_display_fields(self):
        locator = self._sample_bbox_locator()

        result = locator.locate_issue(
            {
                "location": "P001-I0000",
                "evidence": ["P001-I0000"],
            }
        )

        self.assertTrue(result["bbox_lookup_resolved"])
        self.assertEqual(result["best_bbox_match"]["anchor_id"], "P001-I0000")
        self.assertEqual(result["location_anchor_ids"], ["P001-I0000"])
        self.assertEqual(result["evidence_anchor_ids"], ["P001-I0000"])
        self.assertEqual(result["location_original"], "Alpha beta. Gamma delta.")
        self.assertEqual(result["evidence_original"], ["Alpha beta. Gamma delta."])
        self.assertIn("P001-I0000 | Alpha beta. Gamma delta.", result["location_display"])
        self.assertIn("P001-I0000 | Alpha beta. Gamma delta.", result["evidence_display"])

    def test_bbox_locator_normalizes_legacy_sentence_anchor_ids(self):
        locator = self._sample_bbox_locator()

        result = locator.locate_issue(
            {
                "location": "P001-I0000-S01",
                "evidence": ["P001-I0000-S02"],
            }
        )

        self.assertTrue(result["bbox_lookup_resolved"])
        self.assertEqual(result["best_bbox_match"]["anchor_id"], "P001-I0000")
        self.assertEqual(result["location_anchor_ids"], ["P001-I0000"])
        self.assertEqual(result["evidence_anchor_ids"], ["P001-I0000"])
        self.assertIn("P001-I0000 | Alpha beta. Gamma delta.", result["location_display"])

    def test_bbox_locator_resolves_bracketed_anchor_ids(self):
        locator = self._sample_bbox_locator()

        result = locator.locate_issue(
            {
                "location": "[P001-I0000]",
                "evidence": ["[P001-I0000]"],
            }
        )

        self.assertTrue(result["bbox_lookup_resolved"])
        self.assertEqual(result["best_bbox_match"]["anchor_id"], "P001-I0000")
        self.assertEqual(result["best_bbox_match_kind"], "location")
        self.assertEqual(result["location_anchor_ids"], ["P001-I0000"])
        self.assertEqual(result["evidence_anchor_ids"], ["P001-I0000"])
        self.assertIn("P001-I0000 | Alpha beta. Gamma delta.", result["location_display"])

    def test_bbox_locator_prefers_location_match_over_evidence_match(self):
        locator = BBoxLocator(
            {
                "content_list_v2": [
                    [
                        {
                            "type": "paragraph",
                            "bbox": [100, 120, 400, 220],
                            "content": {"text": "Alpha beta. Gamma delta."},
                        },
                        {
                            "type": "paragraph",
                            "bbox": [120, 260, 420, 340],
                            "content": {"text": "Theta lambda. Cache proof."},
                        },
                    ]
                ]
            }
        )

        result = locator.locate_issue(
            {
                "location": "[P001-I0001]",
                "evidence": ["[P001-I0000]"],
            }
        )

        self.assertTrue(result["bbox_lookup_resolved"])
        self.assertEqual(result["best_bbox_match"]["anchor_id"], "P001-I0001")
        self.assertEqual(result["best_bbox_match_kind"], "location")
        self.assertEqual(result["location_anchor_ids"], ["P001-I0001"])
        self.assertEqual(result["evidence_anchor_ids"], ["P001-I0000"])

    def test_bbox_locator_build_anchor_catalog_returns_anchor_ids(self):
        locator = self._sample_bbox_locator()

        catalog = locator.build_anchor_catalog("Alpha beta.")

        self.assertTrue(catalog["entries"])
        self.assertEqual(catalog["entries"][0]["anchor_id"], "P001-I0000")
        self.assertIn("P001-I0000", catalog["catalog_text"])
        self.assertNotIn("-S01", catalog["catalog_text"])

    def test_bbox_locator_build_anchored_text_adds_inline_anchor_ids(self):
        locator = self._sample_bbox_locator()

        anchored = locator.build_anchored_text("Alpha beta. Gamma delta.")

        self.assertIn("[P001-I0000] Alpha beta. Gamma delta.", anchored)
        self.assertNotIn("-S01", anchored)
        self.assertNotIn("-S02", anchored)

    def test_explore_post_process_normalizes_bracketed_anchor_ids(self):
        agent = ExploreAgent()

        issues = agent._post_process_issues(
            [
                {
                    "type": "Claim Distortion",
                    "severity": "medium",
                    "description": "Claim is not fully supported.",
                    "evidence": ["[P001-I0000]"],
                    "location": "[P001-I0000]",
                    "reasoning": "Evidence is weaker than the claim.",
                }
            ],
            default_stage="local",
        )

        self.assertEqual(issues[0]["location"], "P001-I0000")
        self.assertEqual(issues[0]["evidence"], ["P001-I0000"])

    def test_summary_agent_normalizes_bracketed_anchor_ids(self):
        agent = SummaryAgent()

        issues = agent._normalize_issues(
            [
                {
                    "type": "Claim Distortion",
                    "severity": "medium",
                    "description": "Claim is not fully supported.",
                    "evidence": ["[P001-I0000]"],
                    "location": "[P001-I0000]",
                    "reasoning": "Evidence is weaker than the claim.",
                    "source_stage": "local",
                }
            ]
        )

        self.assertEqual(issues[0]["location"], "P001-I0000")
        self.assertEqual(issues[0]["evidence"], ["P001-I0000"])

    def test_explore_agent_normalizes_reasoning_lists_to_multiline_text(self):
        agent = ExploreAgent()

        issues = agent._post_process_issues(
            [
                {
                    "type": "Claim Distortion",
                    "severity": "medium",
                    "description": "Claim is not fully supported.",
                    "evidence": ["P001-I0000"],
                    "location": "P001-I0000",
                    "reasoning": ["1. First point.", "2. Second point."],
                }
            ],
            default_stage="local",
        )

        self.assertEqual(issues[0]["reasoning"], "1. First point.\n2. Second point.")

    def test_summary_agent_normalizes_stringified_reasoning_lists_to_multiline_text(self):
        agent = SummaryAgent()

        issues = agent._normalize_issues(
            [
                {
                    "type": "Claim Distortion",
                    "severity": "medium",
                    "description": "Claim is not fully supported.",
                    "evidence": ["P001-I0000"],
                    "location": "P001-I0000",
                    "reasoning": "['1. First point.', '2. Second point.']",
                    "source_stage": "local",
                }
            ]
        )

        self.assertEqual(issues[0]["reasoning"], "1. First point.\n2. Second point.")

    def test_review_excerpt_deduplicates_lines_already_in_context_window(self):
        chunk_content = "\n".join(
            [
                "ty, and reliability. We utilize over 10,643 source images to ensure content richness.",
                "# B. Scientific Image Manipulation Localization",
                "TABLE I COMPARISON OF BIOMEDICAL IMAGE TAMPERING DATASETS",
                "|Attribute|BioFors|SciSp|RSIID|Ours|",
                "|Scale|1830|1290|39423|31447|",
                "[5] proposed a human-in-the-loop framework for scientific image analysis, relying on traditional forensic tools rather than end-to-end deep learning.",
            ]
        )

        excerpt = draft_main.build_review_excerpt_bundle(chunk_content, max_chars=6500)["text"]

        self.assertEqual(excerpt.count("# B. Scientific Image Manipulation Localization"), 1)
        self.assertEqual(excerpt.count("TABLE I COMPARISON OF BIOMEDICAL IMAGE TAMPERING DATASETS"), 1)
        self.assertEqual(excerpt.count("[5] proposed a human-in-the-loop framework"), 1)

    def test_review_excerpt_does_not_duplicate_line_cut_by_head_window(self):
        keyword_line = (
            "[5] proposed a human-in-the-loop framework for scientific image analysis, "
            "relying on traditional forensic tools rather than end-to-end deep learning."
        )
        chunk_content = "\n".join(
            [
                "A" * 1100,
                keyword_line,
                "Conclusion text.",
            ]
        )

        excerpt = draft_main.build_review_excerpt_bundle(chunk_content, max_chars=6500)["text"]

        self.assertEqual(excerpt.count("[5] proposed a human-in-the-loop framework"), 1)

    def test_chat_completion_client_defaults_to_non_streaming(self):
        class FakeResponse:
            def raise_for_status(self):
                return None

            def json(self):
                return {
                    "choices": [{"message": {"content": '{"ok": true}'}}],
                    "usage": {"prompt_tokens": 3, "completion_tokens": 4, "total_tokens": 7},
                }

        class FakeSession:
            def __init__(self):
                self.last_payload = None
                self.last_stream = None

            def post(self, api_url, headers=None, json=None, timeout=None, stream=False):
                self.last_payload = json
                self.last_stream = stream
                return FakeResponse()

        fake_session = FakeSession()
        client = ChatCompletionClient(
            api_url="https://example.com/v1",
            api_key="key",
            model="model",
            max_retries=1,
        )
        client.session = fake_session

        with patch.object(llm_utils, "LLM_STREAMING_ENABLED", False):
            result = client.complete([{"role": "user", "content": "Hi"}])

        self.assertEqual(result.content, '{"ok": true}')
        self.assertFalse(fake_session.last_stream)
        self.assertNotIn("stream", fake_session.last_payload)
        self.assertFalse(result.streaming)

    def test_chat_completion_client_reads_streaming_sse(self):
        class FakeResponse:
            def raise_for_status(self):
                return None

            def iter_lines(self, decode_unicode=True):
                yield 'data: {"choices":[{"delta":{"content":"Hello "}}]}'
                yield 'data: {"choices":[{"delta":{"content":"world"}}],"usage":{"prompt_tokens":3,"completion_tokens":2,"total_tokens":5}}'
                yield "data: [DONE]"

        class FakeSession:
            def __init__(self):
                self.last_payload = None
                self.last_stream = None

            def post(self, api_url, headers=None, json=None, timeout=None, stream=False):
                self.last_payload = json
                self.last_stream = stream
                return FakeResponse()

        fake_session = FakeSession()
        client = ChatCompletionClient(
            api_url="https://example.com/v1",
            api_key="key",
            model="model",
            max_retries=1,
        )
        client.session = fake_session

        result = client.complete([{"role": "user", "content": "Hi"}], stream=True)

        self.assertEqual(result.content, "Hello world")
        self.assertTrue(fake_session.last_stream)
        self.assertTrue(fake_session.last_payload["stream"])
        self.assertNotIn("enable_thinking", fake_session.last_payload)
        self.assertTrue(result.to_dict()["streaming"])
        self.assertEqual(result.total_tokens, 5)

    def test_chat_completion_client_disables_qwen3_thinking_by_default(self):
        class FakeResponse:
            def raise_for_status(self):
                return None

            def json(self):
                return {
                    "choices": [{"message": {"content": '{"ok": true}'}}],
                    "usage": {"prompt_tokens": 3, "completion_tokens": 4, "total_tokens": 7},
                }

        class FakeSession:
            def __init__(self):
                self.last_payload = None

            def post(self, api_url, headers=None, json=None, timeout=None, stream=False):
                self.last_payload = json
                return FakeResponse()

        fake_session = FakeSession()
        client = ChatCompletionClient(
            api_url="https://example.com/v1",
            api_key="key",
            model="qwen3-32b",
            max_retries=1,
        )
        client.session = fake_session

        with patch.object(llm_utils, "LLM_ENABLE_THINKING", None):
            result = client.complete([{"role": "user", "content": "Hi"}], stream=False)

        self.assertEqual(result.content, '{"ok": true}')
        self.assertFalse(fake_session.last_payload["enable_thinking"])

    def test_chat_completion_client_reads_streaming_output_choices(self):
        class FakeResponse:
            def raise_for_status(self):
                return None

            def iter_lines(self, decode_unicode=True):
                yield 'data: {"output":{"choices":[{"message":{"content":"Hello "}}]}}'
                yield (
                    'data: {"output":{"choices":[{"message":{"content":"world"}}],'
                    '"usage":{"prompt_tokens":3,"completion_tokens":2,"total_tokens":5}}}'
                )
                yield "data: [DONE]"

        class FakeSession:
            def post(self, api_url, headers=None, json=None, timeout=None, stream=False):
                return FakeResponse()

        client = ChatCompletionClient(
            api_url="https://example.com/v1",
            api_key="key",
            model="model",
            max_retries=1,
        )
        client.session = FakeSession()

        result = client.complete([{"role": "user", "content": "Hi"}], stream=True)

        self.assertEqual(result.content, "Hello world")
        self.assertTrue(result.streaming)
        self.assertEqual(result.total_tokens, 5)

    def test_chat_completion_client_falls_back_when_streaming_is_empty(self):
        class FakeStreamResponse:
            def raise_for_status(self):
                return None

            def iter_lines(self, decode_unicode=True):
                yield 'data: {"choices":[{"delta":{"role":"assistant"}}]}'
                yield "data: [DONE]"

        class FakeNonStreamResponse:
            def raise_for_status(self):
                return None

            def json(self):
                return {
                    "choices": [{"message": {"content": '{"ok": true}'}}],
                    "usage": {"prompt_tokens": 3, "completion_tokens": 4, "total_tokens": 7},
                }

        class FakeSession:
            def __init__(self):
                self.calls = []

            def post(self, api_url, headers=None, json=None, timeout=None, stream=False):
                self.calls.append({"payload": json, "stream": stream})
                if stream:
                    return FakeStreamResponse()
                return FakeNonStreamResponse()

        fake_session = FakeSession()
        client = ChatCompletionClient(
            api_url="https://example.com/v1",
            api_key="key",
            model="model",
            max_retries=1,
        )
        client.session = fake_session

        result = client.complete([{"role": "user", "content": "Hi"}], stream=True)

        self.assertEqual(result.content, '{"ok": true}')
        self.assertEqual([call["stream"] for call in fake_session.calls], [True, False])
        self.assertTrue(fake_session.calls[0]["payload"]["stream"])
        self.assertNotIn("stream", fake_session.calls[1]["payload"])
        self.assertFalse(result.streaming)
        self.assertTrue(result.raw_usage["_stream_fallback"])
        self.assertEqual(result.total_tokens, 7)

    def test_agent_logger_writes_input_markdown(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            with patch.object(draft_logger, "LOGS_DIR", Path(temp_dir)):
                logger = draft_logger.AgentLogger()
                logger.log(
                    "PlanAgent",
                    "llm_request",
                    chunk_id=2,
                    input_data={
                        "system_prompt": "System prompt",
                        "user_prompt": "User prompt",
                    },
                    message="Calling planning model",
                )

                md_relative = logger.log_index[-1].get("input_md_filename", "")
                self.assertTrue(md_relative)
                md_path = logger.get_session_dir() / md_relative
                self.assertTrue(md_path.exists())
                content = md_path.read_text(encoding="utf-8")
                self.assertIn("# PlanAgent Input", content)
                self.assertIn("System prompt", content)
                self.assertIn("User prompt", content)

    def test_agent_logger_writes_output_markdown_and_mirrors_explore_io(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            with patch.object(draft_logger, "LOGS_DIR", Path(temp_dir)):
                logger = draft_logger.AgentLogger()
                data_url = "data:image/jpeg;base64,AAA"
                logger.log(
                    "ExploreAgent",
                    "stage_local_llm_input",
                    chunk_id=0,
                    input_data={
                        "llm_messages": [
                            {"role": "system", "content": "System prompt."},
                            {
                                "role": "user",
                                "content": [
                                    {"type": "text", "text": "[P001-I0000] Alpha beta.\n"},
                                    {"type": "image_url", "image_url": {"url": data_url}},
                                ],
                            },
                        ],
                    },
                    message="Starting local check",
                )
                logger.log(
                    "ExploreAgent",
                    "stage_local_llm_output",
                    chunk_id=0,
                    output_data={
                        "llm_output": '{"local_error_list":[{"description":"Description text.","reasoning":"Reasoning text."}]}'
                    },
                    message="Local check produced 1 issue",
                )

                root_input = logger.get_session_dir() / "04_explore_agent" / "input"
                root_output = logger.get_session_dir() / "04_explore_agent" / "output"
                mirrored_inputs = list(root_input.glob("*.input.md"))
                mirrored_outputs = list(root_output.glob("*.output.md"))

                self.assertTrue(mirrored_inputs)
                self.assertTrue(mirrored_outputs)
                input_content = mirrored_inputs[0].read_text(encoding="utf-8")
                self.assertIn("# Model Input", input_content)
                self.assertIn("![LLM image 1](data:image/jpeg;base64,AAA)", input_content)
                self.assertNotIn("step:", input_content)

    def test_vision_agent_writes_per_validation_artifact_directories(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            temp_path = Path(temp_dir)
            screenshot_path = temp_path / "source_evidence.png"
            screenshot_path.write_bytes(b"fake-image-bytes")

            with patch.object(draft_logger, "LOGS_DIR", temp_path):
                logger = draft_logger.AgentLogger()
                agent = VisionValidationAgent(logger=logger)
                llm_result = LLMCallResult(
                    content='{"decision":"keep","confidence":"high","reason":"Supported by screenshot."}',
                    elapsed_seconds=0.1,
                    model="mock-vision-model",
                    prompt_tokens=10,
                    completion_tokens=8,
                    total_tokens=18,
                    usage_source="estimated",
                    request_chars=100,
                    response_chars=64,
                    raw_usage={},
                )

                with patch.object(VisionValidationAgent, "enabled", new_callable=PropertyMock, return_value=True):
                    with patch.object(VisionValidationAgent, "_call_llm", return_value=llm_result):
                        result = agent.validate_issue(
                            issue={
                                "type": "Claim Distortion",
                                "severity": "medium",
                                "description": "Claim appears unsupported.",
                                "evidence": ["P001-I0001"],
                                "location": "P001-I0000",
                                "reasoning": "Need screenshot verification.",
                                "chunk_id": 2,
                            },
                            issue_index=1,
                            chunk_id=2,
                            screenshots=[
                                {
                                    "kind": "evidence",
                                    "page": 10,
                                    "bbox": [10, 20, 30, 40],
                                    "page_bbox": [1, 2, 3, 4],
                                    "bbox_coordinate_system": "normalized_1000",
                                    "matched_text": "Alpha beta",
                                    "local_path": str(screenshot_path),
                                }
                            ],
                        )

                case_dir = logger.get_session_dir() / "13_vision_agent" / "validations" / "chunk0002_issue0001"
                self.assertTrue((case_dir / "images").exists())
                self.assertTrue((case_dir / "input").exists())
                self.assertTrue((case_dir / "output").exists())

                copied_images = list((case_dir / "images").glob("*.png"))
                self.assertEqual(len(copied_images), 1)

                request_md = (case_dir / "input" / "model_request.md").read_text(encoding="utf-8")
                self.assertIn("# Vision Model Request", request_md)
                self.assertIn("## Images Sent To Model", request_md)
                self.assertIn("## User Prompt", request_md)
                self.assertIn("../images/01_evidence_page010.png", request_md)

                parsed_result = json.loads((case_dir / "output" / "parsed_result.json").read_text(encoding="utf-8"))
                self.assertEqual(parsed_result["decision"], "keep")
                self.assertEqual(result["decision"], "keep")

    def test_build_multimodal_user_content_embeds_images_at_markdown_position(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            image_path = Path(temp_dir) / "figure.jpg"
            image_path.write_bytes(b"fake-image")

            content = build_multimodal_user_content(
                "Before image.\n![](images/figure.jpg)\nAfter image.",
                [
                    {
                        "local_path": str(image_path),
                        "img_path": "images/figure.jpg",
                        "source_image_paths": ["images/figure.jpg"],
                    }
                ],
                min_pixels=1,
                max_pixels=10,
            )

        self.assertIsInstance(content, list)
        self.assertEqual(content[0]["type"], "text")
        self.assertIn("Before image.", content[0]["text"])
        self.assertEqual(content[1]["type"], "image_url")
        self.assertTrue(content[1]["image_url"]["url"].startswith("data:image/jpeg;base64,"))
        self.assertEqual(content[2]["type"], "text")
        self.assertIn("After image.", content[2]["text"])

    def test_process_chunk_review_runs_staged_search_finalize_flow(self):
        call_order = []

        class DummyLogger:
            def log(self, *args, **kwargs):
                return None

            def progress(self, *args, **kwargs):
                return None

        local_issue = {
            "type": "Citation Fabrication",
            "severity": "high",
            "description": "Local issue",
            "evidence": ["P001-I0000"],
            "location": "P001-I0000",
            "reasoning": "Local reasoning.",
            "source_stage": "local",
        }
        global_issue = {
            "type": "Context Misalignment",
            "severity": "medium",
            "description": "Global issue",
            "evidence": ["P001-I0000"],
            "location": "P001-I0000",
            "reasoning": "Global reasoning.",
            "source_stage": "global",
        }
        merged_issue = {
            "type": "Citation Fabrication",
            "severity": "high",
            "description": "Merged issue",
            "evidence": ["P001-I0000"],
            "location": "P001-I0000",
            "reasoning": "Merged reasoning.",
            "source_stage": "local+global",
        }

        class FakeExploreAgent:
            def __init__(self, logger=None):
                self.logger = logger

            @staticmethod
            def _summarize_images(image_inputs):
                return image_inputs

            @staticmethod
            def _summarize_issues(issues):
                return f"{len(issues)} issues"

            def run_local_initial(self, **kwargs):
                call_order.append("local_initial")
                assert "[P001-I0000] Alpha beta. Gamma delta." in kwargs["chunk_content"]
                return {
                    "local_error_list": [dict(local_issue)],
                    "search_requests": [
                        {"request_id": "local-1", "goal": "verify local", "query": "local query"}
                    ],
                    "_llm_metrics": {"stage": "local_initial"},
                }

            def run_local_finalize(self, **kwargs):
                call_order.append("local_finalize")
                self.logger and self.logger.log
                assert kwargs["search_results"][0]["request_id"] == "local-1"
                assert "[P001-I0000] Alpha beta. Gamma delta." in kwargs["chunk_content"]
                issue = dict(local_issue)
                issue["description"] = "Local issue refined"
                return {
                    "local_error_list": [issue],
                    "_llm_metrics": {"stage": "local_finalize"},
                }

            def run_global_initial(self, **kwargs):
                call_order.append("global_initial")
                assert "<current chunk>" in kwargs["document_overview"]
                assert "</current chunk>" in kwargs["document_overview"]
                assert "[P001-I0000] Alpha beta. Gamma delta." in kwargs["document_overview"]
                assert "chunk_content" not in kwargs
                assert "neighbor_context" not in kwargs
                assert "global_chunk_map" not in kwargs
                assert "local_error_list" not in kwargs
                assert "plan_output" not in kwargs
                return {
                    "global_error_list": [dict(global_issue)],
                    "search_requests": [
                        {"request_id": "global-1", "goal": "verify global", "query": "global query"}
                    ],
                    "_llm_metrics": {"stage": "global_initial"},
                }

            def run_global_finalize(self, **kwargs):
                call_order.append("global_finalize")
                assert kwargs["search_results"][0]["request_id"] == "global-1"
                assert "<current chunk>" in kwargs["document_overview"]
                assert "[P001-I0000] Alpha beta. Gamma delta." in kwargs["document_overview"]
                assert "chunk_content" not in kwargs
                assert "neighbor_context" not in kwargs
                assert "global_chunk_map" not in kwargs
                issue = dict(global_issue)
                issue["description"] = "Global issue refined"
                return {
                    "global_error_list": [issue],
                    "_llm_metrics": {"stage": "global_finalize"},
                }

            def merge_error_lists(self, **kwargs):
                call_order.append("merge")
                assert kwargs["local_error_list"][0]["description"] == "Local issue refined"
                assert kwargs["global_error_list"][0]["description"] == "Global issue refined"
                return {
                    "error_list": [dict(merged_issue)],
                    "_llm_metrics": {"stage": "merge"},
                }

        class FakeSearchAgent:
            enabled = True

            def __init__(self, logger=None):
                self.logger = logger

            def run_requests(self, *, search_requests, chunk_id=None):
                call_order.append(f"search:{search_requests[0]['request_id']}")
                return {
                    "search_results": [
                        {
                            "request_id": search_requests[0]["request_id"],
                            "query": search_requests[0]["query"],
                            "summary": "search summary",
                            "sources": [{"title": "source", "url": "https://example.com", "snippet": ""}],
                        }
                    ],
                    "raw_search_results": [],
                    "_llm_metrics": {"stage": f"search:{search_requests[0]['request_id']}"},
                    "search_performed": True,
                }

        class FakeSummaryAgent:
            def __init__(self, logger=None):
                self.logger = logger

            def summarize(self, *, candidate_issues, **kwargs):
                call_order.append("summary")
                return {"issues": candidate_issues, "_llm_metrics": {"stage": "summary"}}

        with (
            patch.object(draft_main, "ExploreAgent", FakeExploreAgent),
            patch.object(draft_main, "SearchAgent", FakeSearchAgent),
            patch.object(draft_main, "SummaryAgent", FakeSummaryAgent),
        ):
            locator = self._sample_bbox_locator()
            result = draft_main.process_chunk_review(
                chunk_record={
                    "chunk_id": 0,
                    "plan_output": {
                        "section_role": "Introduction",
                        "chunk_purpose": "Explain background",
                        "core_content": "Core content",
                        "visual_element_role": "No visual elements.",
                    },
                    "review_excerpt": "Alpha beta. Gamma delta.",
                    "chunk_images": [],
                    "neighbor_context": "Alpha beta.",
                    "llm_metrics_list": [],
                    "review_audit": {},
                    "explore_document_overview": "Alpha beta. Gamma delta.",
                },
                document_overview="Alpha beta. Gamma delta.",
                full_document_text="Alpha beta. Gamma delta.",
                cache_dir=Path("."),
                logger=DummyLogger(),
                vision_enabled=False,
                search_enabled=True,
                pdf_path="",
                bbox_locator=locator,
            )

        self.assertEqual(
            call_order,
            [
                "local_initial",
                "search:local-1",
                "local_finalize",
                "global_initial",
                "search:global-1",
                "global_finalize",
                "merge",
                "summary",
            ],
        )
        self.assertEqual(result["issues"][0]["description"], "Merged issue")
        self.assertEqual(len(result["issues"][0]["search_result"]["stages"]), 2)
        self.assertTrue(result["issues"][0]["bbox_lookup_resolved"])
        self.assertEqual(result["explore_output"]["local_search_results"][0]["request_id"], "local-1")
        self.assertEqual(result["explore_output"]["global_search_results"][0]["request_id"], "global-1")

    def test_process_chunk_review_preserves_local_issues_when_global_fails(self):
        call_order = []

        class DummyLogger:
            def log(self, *args, **kwargs):
                return None

            def progress(self, *args, **kwargs):
                return None

        local_issue = {
            "type": "Language Expression",
            "severity": "medium",
            "description": "Local issue survives.",
            "evidence": ["P001-I0000"],
            "location": "P001-I0000",
            "reasoning": "Local reasoning.",
            "source_stage": "local",
        }

        class FakeExploreAgent:
            def __init__(self, logger=None):
                self.logger = logger

            @staticmethod
            def _summarize_images(image_inputs):
                return image_inputs

            @staticmethod
            def _summarize_issues(issues):
                return f"{len(issues)} issues"

            def run_local_initial(self, **kwargs):
                call_order.append("local_initial")
                return {
                    "local_error_list": [dict(local_issue)],
                    "search_requests": [],
                    "_llm_metrics": {"stage": "local_initial"},
                }

            def run_global_initial(self, **kwargs):
                call_order.append("global_initial")
                raise TimeoutError("global timeout")

            def merge_error_lists(self, **kwargs):
                raise AssertionError("merge_error_lists should be skipped when search is disabled")

        class FakeSummaryAgent:
            def __init__(self, logger=None):
                self.logger = logger

            def summarize(self, *, candidate_issues, **kwargs):
                call_order.append("summary")
                return {"issues": candidate_issues, "_llm_metrics": {"stage": "summary"}}

        with (
            patch.object(draft_main, "ExploreAgent", FakeExploreAgent),
            patch.object(draft_main, "SummaryAgent", FakeSummaryAgent),
        ):
            result = draft_main.process_chunk_review(
                chunk_record={
                    "chunk_id": 0,
                    "plan_output": {
                        "section_role": "Introduction",
                        "chunk_purpose": "Explain background",
                        "core_content": "Core content",
                        "visual_element_role": "No visual elements.",
                    },
                    "review_excerpt": "Alpha beta. Gamma delta.",
                    "chunk_images": [],
                    "neighbor_context": "Alpha beta.",
                    "llm_metrics_list": [],
                    "review_audit": {},
                    "explore_document_overview": "Alpha beta. Gamma delta.",
                },
                document_overview="Alpha beta. Gamma delta.",
                full_document_text="Alpha beta. Gamma delta.",
                cache_dir=Path("."),
                logger=DummyLogger(),
                vision_enabled=False,
                search_enabled=False,
                pdf_path="",
                bbox_locator=None,
            )

        self.assertEqual(call_order, ["local_initial", "global_initial", "summary"])
        self.assertEqual(len(result["issues"]), 1)
        self.assertEqual(result["issues"][0]["description"], "Local issue survives.")

    def test_process_chunk_review_runs_local_checks_for_each_local_subchunk(self):
        call_order = []

        class DummyLogger:
            def log(self, *args, **kwargs):
                return None

            def progress(self, *args, **kwargs):
                return None

        class FakeExploreAgent:
            def __init__(self, logger=None):
                self.logger = logger

            @staticmethod
            def _summarize_images(image_inputs):
                return image_inputs

            @staticmethod
            def _summarize_issues(issues):
                return f"{len(issues)} issues"

            def run_local_initial(self, **kwargs):
                chunk_content = kwargs["chunk_content"]
                if "Alpha beta." in chunk_content:
                    call_order.append("local_initial:part1")
                    description = "Local issue from part 1"
                else:
                    call_order.append("local_initial:part2")
                    description = "Local issue from part 2"
                return {
                    "local_error_list": [
                        {
                            "type": "Language Expression",
                            "severity": "medium",
                            "description": description,
                            "evidence": ["P001-I0000"],
                            "location": "P001-I0000",
                            "reasoning": "Local reasoning.",
                            "source_stage": "local",
                        }
                    ],
                    "search_requests": [],
                    "_llm_metrics": {"stage": "local_initial"},
                }

            def run_global_initial(self, **kwargs):
                call_order.append("global_initial")
                assert "<current chunk>" in kwargs["document_overview"]
                assert "Alpha beta." in kwargs["document_overview"]
                assert "Gamma delta." in kwargs["document_overview"]
                return {
                    "global_error_list": [
                        {
                            "type": "Context Misalignment",
                            "severity": "high",
                            "description": "Global issue.",
                            "evidence": ["P001-I0000"],
                            "location": "P001-I0000",
                            "reasoning": "Global reasoning.",
                            "source_stage": "global",
                        }
                    ],
                    "search_requests": [],
                    "_llm_metrics": {"stage": "global_initial"},
                }

            def merge_error_lists(self, **kwargs):
                raise AssertionError("merge_error_lists should be skipped when search is disabled")

        class FakeSummaryAgent:
            def __init__(self, logger=None):
                self.logger = logger

            def summarize(self, *, candidate_issues, **kwargs):
                call_order.append("summary")
                return {"issues": candidate_issues, "_llm_metrics": {"stage": "summary"}}

        with (
            patch.object(draft_main, "ExploreAgent", FakeExploreAgent),
            patch.object(draft_main, "SummaryAgent", FakeSummaryAgent),
        ):
            result = draft_main.process_chunk_review(
                chunk_record={
                    "chunk_id": 0,
                    "plan_output": {
                        "section_role": "Introduction",
                        "chunk_purpose": "Explain background",
                        "core_content": "Core content",
                        "visual_element_role": "No visual elements.",
                    },
                    "review_excerpt": "Alpha beta.\n\nGamma delta.",
                    "chunk_images": [],
                    "neighbor_context": "",
                    "llm_metrics_list": [],
                    "review_audit": {},
                    "current_chunk_text": "Alpha beta.\n\nGamma delta.",
                    "explore_document_overview": "Alpha beta.\n\nGamma delta.",
                    "local_chunk_records": [
                        {
                            "local_chunk_id": 0,
                            "review_excerpt": "Alpha beta.",
                            "current_chunk_text": "Alpha beta.",
                            "char_count": 11,
                            "review_audit": {},
                        },
                        {
                            "local_chunk_id": 1,
                            "review_excerpt": "Gamma delta.",
                            "current_chunk_text": "Gamma delta.",
                            "char_count": 12,
                            "review_audit": {},
                        },
                    ],
                },
                document_overview="Alpha beta.\n\nGamma delta.",
                full_document_text="Alpha beta.\n\nGamma delta.",
                cache_dir=Path("."),
                logger=DummyLogger(),
                vision_enabled=False,
                search_enabled=False,
                pdf_path="",
                bbox_locator=None,
            )

        self.assertEqual(
            call_order,
            ["local_initial:part1", "local_initial:part2", "global_initial", "summary"],
        )
        self.assertEqual(
            {issue["description"] for issue in result["issues"]},
            {"Local issue from part 1", "Local issue from part 2", "Global issue."},
        )

    def test_process_chunk_review_skips_final_merge_when_search_is_disabled(self):
        call_order = []

        class DummyLogger:
            def log(self, *args, **kwargs):
                return None

            def progress(self, *args, **kwargs):
                return None

        local_issue = {
            "type": "Language Expression",
            "severity": "medium",
            "description": "Local issue.",
            "evidence": ["P001-I0000"],
            "location": "P001-I0000",
            "reasoning": "Local reasoning.",
            "source_stage": "local",
        }
        global_issue = {
            "type": "Context Misalignment",
            "severity": "high",
            "description": "Global issue.",
            "evidence": ["P001-I0000"],
            "location": "P001-I0000",
            "reasoning": "Global reasoning.",
            "source_stage": "global",
        }

        class FakeExploreAgent:
            def __init__(self, logger=None):
                self.logger = logger

            @staticmethod
            def _summarize_images(image_inputs):
                return image_inputs

            @staticmethod
            def _summarize_issues(issues):
                return f"{len(issues)} issues"

            def run_local_initial(self, **kwargs):
                call_order.append("local_initial")
                return {
                    "local_error_list": [dict(local_issue)],
                    "search_requests": [],
                    "_llm_metrics": {"stage": "local_initial"},
                }

            def run_global_initial(self, **kwargs):
                call_order.append("global_initial")
                return {
                    "global_error_list": [dict(global_issue)],
                    "search_requests": [],
                    "_llm_metrics": {"stage": "global_initial"},
                }

            def merge_error_lists(self, **kwargs):
                raise AssertionError("merge_error_lists should be skipped when search is disabled")

        class FakeSummaryAgent:
            def __init__(self, logger=None):
                self.logger = logger

            def summarize(self, *, candidate_issues, **kwargs):
                call_order.append("summary")
                descriptions = {item["description"] for item in candidate_issues}
                assert descriptions == {"Local issue.", "Global issue."}
                return {"issues": candidate_issues, "_llm_metrics": {"stage": "summary"}}

        with (
            patch.object(draft_main, "ExploreAgent", FakeExploreAgent),
            patch.object(draft_main, "SummaryAgent", FakeSummaryAgent),
        ):
            result = draft_main.process_chunk_review(
                chunk_record={
                    "chunk_id": 0,
                    "plan_output": {
                        "section_role": "Introduction",
                        "chunk_purpose": "Explain background",
                        "core_content": "Core content",
                        "visual_element_role": "No visual elements.",
                    },
                    "review_excerpt": "Alpha beta. Gamma delta.",
                    "chunk_images": [],
                    "neighbor_context": "Alpha beta.",
                    "llm_metrics_list": [],
                    "review_audit": {},
                    "explore_document_overview": "Alpha beta. Gamma delta.",
                },
                document_overview="Alpha beta. Gamma delta.",
                full_document_text="Alpha beta. Gamma delta.",
                cache_dir=Path("."),
                logger=DummyLogger(),
                vision_enabled=False,
                search_enabled=False,
                pdf_path="",
                bbox_locator=None,
            )

        self.assertEqual(call_order, ["local_initial", "global_initial", "summary"])
        self.assertEqual({issue["description"] for issue in result["issues"]}, {"Local issue.", "Global issue."})

    def test_search_organize_prompt_includes_current_chunk_context(self):
        rendered = prompt_loader.render_prompt_section_template(
            "search/organize_results_prompt.md",
            "user",
            current_chunk="Alpha beta. Gamma delta.",
            search_requests_markdown="- request_id: local-1\n  goal: verify\n  query: alpha",
            raw_search_results_markdown="No raw search results.",
        )

        self.assertIn("Alpha beta. Gamma delta.", rendered)
        self.assertIn("request_id: local-1", rendered)

    def test_issue_review_decision_prefers_recheck_validation(self):
        issue = {
            "vision_validation": {"decision": "keep"},
            "recheck_validation": {"decision": "drop"},
        }

        self.assertEqual(get_issue_review_decision(issue), "drop")

    def test_recheck_agent_limits_vision_to_language_and_formula(self):
        self.assertTrue(RecheckAgent.should_run_vision("Language Expression"))
        self.assertTrue(RecheckAgent.should_run_vision("Formula Computation"))
        self.assertFalse(RecheckAgent.should_run_vision("Background Knowledge"))

    def test_recheck_text_prompt_uses_full_document_without_plan_or_search(self):
        rendered = prompt_loader.render_prompt_section_template(
            "recheck_text_prompt.md",
            "user",
            full_document_text="Full paper text.",
            chunk_id=3,
            issues_json='[{"issue_index": 1, "description": "Alpha"}]',
        )

        self.assertIn("Full paper text.", rendered)
        self.assertIn("chunk_id=3", rendered)
        self.assertIn('"issue_index": 1', rendered)
        self.assertNotIn("Plan", rendered)
        self.assertNotIn("Search result", rendered)

    def test_text_recheck_normalize_chunk_results_downgrades_uncertain_drop(self):
        normalized = TextRecheckAgent._normalize_chunk_results(
            {
                "issues": [
                    {
                        "issue_index": 1,
                        "decision": "drop",
                        "confidence": "medium",
                        "reason": "Evidence is ambiguous.",
                    }
                ]
            },
            expected_issue_count=1,
        )

        self.assertEqual(normalized[0]["decision"], "review")
        self.assertIn("Downgraded to review", normalized[0]["reason"])

    def test_recheck_aggregate_requires_vision_agreement_for_drop_when_vision_runs(self):
        combined = RecheckAgent._combine_decisions(
            text_validation={"decision": "drop", "confidence": "high", "reason": "Clearly contradicted."},
            vision_validation={"decision": "review", "confidence": "medium", "reason": "Screenshot not conclusive."},
        )

        self.assertEqual(combined["decision"], "review")

    def test_vision_validation_normalize_downgrades_uncertain_drop(self):
        normalized = VisionValidationAgent._normalize_result(
            {
                "decision": "drop",
                "confidence": "medium",
                "reason": "The screenshot is unclear.",
            }
        )

        self.assertEqual(normalized["decision"], "review")
        self.assertIn("Downgraded to review", normalized["reason"])

    def test_normalize_chat_api_url_accepts_base_urls(self):
        self.assertEqual(
            llm_utils.normalize_chat_api_url("https://dashscope.aliyuncs.com/compatible-mode/v1"),
            "https://dashscope.aliyuncs.com/compatible-mode/v1/chat/completions",
        )
        self.assertEqual(
            llm_utils.normalize_chat_api_url("https://api.openai.com/v1"),
            "https://api.openai.com/v1/chat/completions",
        )
        self.assertEqual(
            llm_utils.normalize_chat_api_url("https://api.openai.com"),
            "https://api.openai.com/v1/chat/completions",
        )

    def test_pdf_issue_screenshot_renderer_uses_tight_crop_and_attaches_ocr_text(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            pdf_path = Path(temp_dir) / "sample.pdf"
            output_dir = Path(temp_dir) / "shots"
            document = fitz.open()
            page = document.new_page(width=200, height=200)
            page.insert_text((36, 48), "Alpha beta gamma delta")
            document.save(pdf_path)
            document.close()

            renderer = PDFIssueScreenshotRenderer(str(pdf_path), output_dir, bbox_normalized_size=1000)
            try:
                screenshots = renderer.render_issue(
                    {
                        "location_bbox_matches": [
                            {
                                "page": 1,
                                "bbox": [150, 150, 850, 350],
                                "matched_text": "Alpha beta gamma delta",
                            }
                        ]
                    },
                    issue_index=1,
                )
            finally:
                renderer.close()

            self.assertEqual(len(screenshots), 1)
            self.assertEqual(screenshots[0]["clip_bbox"], screenshots[0]["page_bbox"])
            self.assertIn("ocr_text", screenshots[0])
            self.assertIn(screenshots[0]["ocr_source"], {"paddleocr", "tesseract", "pdf_clip_text", "none"})
            self.assertTrue(Path(screenshots[0]["local_path"]).exists())

    def test_config_validation_uses_cached_success_when_config_is_unchanged(self):
        runtime_config = {
            "mineru_api_url": "https://mineru.net/api/v4",
            "mineru_api_key": "mineru-key",
            "review_api_url": "https://dashscope.aliyuncs.com/compatible-mode/v1",
            "review_api_key": "review-key",
            "review_model": "qwen-plus",
            "recheck_llm_api_url": "",
            "recheck_llm_api_key": "",
            "recheck_llm_model": "",
            "recheck_vlm_api_url": "",
            "recheck_vlm_api_key": "",
            "recheck_vlm_model": "",
            "search_engine": "duckduckgo",
            "serper_api_key": "",
        }

        with tempfile.TemporaryDirectory() as temp_dir:
            cache_path = Path(temp_dir) / "config_validation_cache.json"
            with (
                patch.object(config_validator, "_validate_mineru_connection") as mineru_check,
                patch.object(config_validator, "_validate_chat_model") as model_check,
            ):
                first = config_validator.validate_runtime_configuration(
                    runtime_config=runtime_config,
                    cache_path=cache_path,
                )
                second = config_validator.validate_runtime_configuration(
                    runtime_config=runtime_config,
                    cache_path=cache_path,
                )

        self.assertFalse(first["cached"])
        self.assertTrue(second["cached"])
        mineru_check.assert_called_once()
        model_check.assert_called_once()

    def test_config_validation_rejects_partial_optional_recheck_configuration(self):
        runtime_config = {
            "mineru_api_url": "https://mineru.net/api/v4",
            "mineru_api_key": "mineru-key",
            "review_api_url": "https://dashscope.aliyuncs.com/compatible-mode/v1",
            "review_api_key": "review-key",
            "review_model": "qwen-plus",
            "recheck_llm_api_url": "https://api.openai.com/v1",
            "recheck_llm_api_key": "",
            "recheck_llm_model": "",
            "recheck_vlm_api_url": "",
            "recheck_vlm_api_key": "",
            "recheck_vlm_model": "",
            "search_engine": "duckduckgo",
            "serper_api_key": "",
        }

        with tempfile.TemporaryDirectory() as temp_dir:
            cache_path = Path(temp_dir) / "config_validation_cache.json"
            with (
                patch.object(config_validator, "_validate_mineru_connection"),
                patch.object(config_validator, "_validate_chat_model"),
            ):
                with self.assertRaises(config_validator.ConfigValidationError) as ctx:
                    config_validator.validate_runtime_configuration(
                        runtime_config=runtime_config,
                        cache_path=cache_path,
                    )

        self.assertIn("Recheck LLM configuration is incomplete", str(ctx.exception))

    def test_export_report_html_matches_detection_issue_card_layout(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            pdf_path = Path(temp_dir) / "sample.pdf"
            document = fitz.open()
            page = document.new_page(width=200, height=200)
            page.insert_text((36, 48), "Alpha beta gamma delta")
            document.save(pdf_path)
            document.close()

            html = render_export_report_html(
                {
                    "report_language": "en",
                    "bbox_debug_summary": {},
                    "issues": [
                        {
                            "client_id": "issue-1",
                            "chunk_id": 1,
                            "type": "Language Expression",
                            "severity": "medium",
                            "description": "Description copy.",
                            "reasoning": "Reasoning copy.",
                            "location_original": "P001-I0001",
                            "best_bbox_match": {"page": 1, "bbox": [100, 100, 300, 180]},
                        }
                    ],
                },
                str(pdf_path),
            )

        self.assertNotIn('id="issueSearch"', html)
        self.assertIn('ui.description || (REPORT.language === "zh"', html)
        self.assertIn('issueReasoningText(issue)', html)
        self.assertIn('issueLocationText(issue)', html)
        self.assertIn('id="locationFocusGroup"', html)
        self.assertIn('Issue Evidence', html)
        self.assertIn("currentType === type", html)

    def test_normalize_chunk_id_list_filters_invalid_values(self):
        self.assertEqual(
            draft_main.normalize_chunk_id_list([3, "1", -1, "x", 3, 2, None]),
            [1, 2, 3],
        )

    def test_task_manager_build_resume_state_uses_partial_result_chunk_ids(self):
        task = Task("task-1", "standard", {}, pdf_path="paper.pdf", pdf_name="paper.pdf")
        task.logs = [
            {
                "ts": "2026-04-13T10:00:00",
                "agent": "Main",
                "stage": "chunk_complete",
                "message": "Completed chunk 0",
                "data": {"chunk_id": 0},
            },
            {
                "ts": "2026-04-13T10:01:00",
                "agent": "Main",
                "stage": "chunk_complete",
                "message": "Completed chunk 2",
                "data": {"chunk_id": 2},
            },
        ]
        task.result = {
            "total_chunks": 4,
            "processed_chunk_ids": [0, 2],
            "issues": [
                {"chunk_id": 0, "description": "Issue A"},
                {"chunk_id": 2, "description": "Issue B"},
            ],
        }

        resume_state = TaskManager.build_resume_state(task)

        self.assertEqual(resume_state["completed_chunk_ids"], [0, 2])
        self.assertEqual(resume_state["total_chunks"], 4)
        self.assertEqual({issue["description"] for issue in resume_state["issues"]}, {"Issue A", "Issue B"})

    def test_export_annotated_pdf_bytes_adds_pdf_annotations(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            pdf_path = Path(temp_dir) / "sample.pdf"
            document = fitz.open()
            page = document.new_page(width=200, height=200)
            page.insert_text((36, 48), "Alpha beta gamma delta")
            document.save(pdf_path)
            document.close()

            annotated_bytes = export_annotated_pdf_bytes(
                {
                    "issues": [
                        {
                            "type": "Language Expression",
                            "description": "A wording issue.",
                            "reasoning": "The phrase is malformed.",
                            "location_bbox_matches": [
                                {
                                    "page": 1,
                                    "bbox": [150, 150, 850, 350],
                                    "score": 1.0,
                                }
                            ],
                            "recheck_validation": {"decision": "keep"},
                        }
                    ]
                },
                str(pdf_path),
            )

            annotated = fitz.open(stream=annotated_bytes, filetype="pdf")
            try:
                annotation_summaries = [
                    {
                        "type": annot.type[1],
                        "has_popup": annot.has_popup,
                        "popup_width": float(annot.popup_rect.width or 0.0),
                    }
                    for annot in (annotated[0].annots() or [])
                ]
                page_count = annotated.page_count
            finally:
                annotated.close()

        self.assertEqual(page_count, 1)
        self.assertGreaterEqual(len(annotation_summaries), 2)
        text_annotations = [item for item in annotation_summaries if item["type"] == "Text"]
        self.assertTrue(text_annotations)
        self.assertTrue(any(item["has_popup"] for item in text_annotations))
        self.assertTrue(any(item["popup_width"] >= 150 for item in text_annotations))


if __name__ == "__main__":
    unittest.main()
