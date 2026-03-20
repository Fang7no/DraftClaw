from __future__ import annotations

from pathlib import Path

from draftclaw import DraftClaw, DraftClawSettings, IOOptions, LLMOptions, ModeName, ParserOptions, StandardOptions, run_document

# Required settings.
# Replace this with the document you want to inspect.
INPUT_FILE = Path("./test_pdf/whu.pdf")
# Required: replace with your real API key.
API_KEY = "your_api_key"

# Common settings.
# Keep this enabled for the normal review flow. Set to False for parse-only runs.
RUN_REVIEW = True
# Use `standard` for steadier review and `fast` for quicker scans.
RUN_MODE = ModeName.STANDARD
# Optional label used in the generated run folder name.
RUN_NAME = "demo_review"
# Change this only when using a non-default OpenAI-compatible provider.
BASE_URL = "https://api.openai.com/v1"
# Change this to the model you want to use.
MODEL = "gpt-4o-mini"
# Root output directory for runs, caches, and copied inputs.
WORKING_DIR = Path("output")

# Advanced settings.
# Usually keep this enabled so repeated errors can be merged more cleanly.
ENABLE_MERGE_AGENT = True
# Keep this enabled for txt/md inputs unless you need full parser parity.
TEXT_FAST_PATH = True
# In-process cache avoids repeated parsing in the same Python process.
CACHE_IN_PROCESS = True
# Disk cache avoids repeated parsing across separate runs.
CACHE_ON_DISK = True
# Leave this at 8 unless you need different PDF chunking for docling.
DOCLING_PAGE_CHUNK_SIZE = 8
# `0` means auto: nearest odd number to chars/5000, capped at 19.
CHUNK_COUNT = 0
# Request timeout in seconds.
LLM_TIMEOUT_SEC = 60.0


def build_settings() -> DraftClawSettings:
    return DraftClawSettings(
        llm=LLMOptions(
            api_key=API_KEY,
            base_url=BASE_URL,
            model=MODEL,
            timeout_sec=LLM_TIMEOUT_SEC,
            enable_merge_agent=ENABLE_MERGE_AGENT,
        ),
        io=IOOptions(
            working_dir=str(WORKING_DIR),
        ),
        parser=ParserOptions(
            text_fast_path=TEXT_FAST_PATH,
            cache_in_process=CACHE_IN_PROCESS,
            cache_on_disk=CACHE_ON_DISK,
            docling_page_chunk_size=DOCLING_PAGE_CHUNK_SIZE,
        ),
        standard=StandardOptions(
            target_chunks=CHUNK_COUNT,
        ),
    )


def main() -> None:
    outcome = run_document(
        INPUT_FILE,
        review=RUN_REVIEW,
        mode=RUN_MODE,
        run_name=RUN_NAME,
        settings=build_settings(),
    )

    if outcome.review is None:
        print(outcome.document.text[:500])
        return

    print("\nReview result:")
    print(DraftClaw.dump_result(outcome.review.result))
    print(f"\nArtifacts: {outcome.review.result_json}")


if __name__ == "__main__":
    main()
