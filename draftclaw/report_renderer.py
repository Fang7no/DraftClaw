"""
Self-contained HTML renderer for DraftClaw review reports.
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any, Dict, List


TYPE_COLOR_MAP = {
    "Claim Distortion": "#b45309",
    "Context Misalignment": "#2563eb",
    "Citation Fabrication": "#dc2626",
    "Formula Computation": "#7c3aed",
    "Language Expression": "#0f766e",
    "Multimodal Inconsistency": "#0f766e",
}


UI_TEXT = {
    "zh": {
        "title_suffix": "DraftClaw \u62a5\u544a",
        "eyebrow": "Evidence Navigator",
        "language": "\u62a5\u544a\u8bed\u8a00",
        "issues": "\u95ee\u9898\u6570",
        "chunks": "Chunk \u6570",
        "bbox": "BBox \u547d\u4e2d",
        "tokens": "\u603b Token",
        "mode": "\u591a\u6a21\u6001",
        "toolbar_groups": "\u95ee\u9898\u5206\u7c7b",
        "toolbar_groups_hint": "\u6309\u95ee\u9898\u7c7b\u578b\u5207\u6362\u5de6\u4fa7\u5bfc\u822a\u548c\u53f3\u4fa7\u8be6\u60c5\u3002",
        "toolbar_nav": "\u95ee\u9898\u5bfc\u822a",
        "toolbar_detail": "\u5f53\u524d\u95ee\u9898",
        "prev": "\u4e0a\u4e00\u4e2a",
        "next": "\u4e0b\u4e00\u4e2a",
        "empty_group": "\u5f53\u524d\u6ca1\u6709\u53ef\u5c55\u793a\u7684\u95ee\u9898\u3002",
        "empty_detail": "\u9009\u62e9\u4e00\u4e2a\u95ee\u9898\u540e\u67e5\u770b\u8be6\u60c5\u3002",
        "detail_id": "\u95ee\u9898",
        "detail_description": "\u95ee\u9898\u63cf\u8ff0",
        "detail_evidence": "\u8bc1\u636e\u53e5",
        "detail_location": "\u4f4d\u7f6e\u53e5",
        "detail_reasoning": "\u63a8\u7406\u8bf4\u660e",
        "detail_context": "\u539f\u6587\u4e0a\u4e0b\u6587",
        "detail_bbox": "BBox \u5b9a\u4f4d",
        "detail_chunk": "Chunk",
        "detail_source": "\u6765\u6e90",
        "detail_score": "\u5206\u6570",
        "detail_page": "\u9875\u7801",
        "detail_coords": "\u5750\u6807",
        "matched_paragraph": "\u5339\u914d\u6bb5\u843d",
        "group_meta_default": "\u9009\u62e9\u95ee\u9898\u7c7b\u578b\u540e\u67e5\u770b\u5bf9\u5e94\u95ee\u9898\u3002",
        "navigator_meta_default": "\u5f53\u524d\u672a\u9009\u62e9\u95ee\u9898",
        "detail_meta_default": "\u5f53\u524d\u672a\u9009\u62e9\u95ee\u9898",
        "report_summary": "\u672c\u62a5\u544a\u5305\u542b {issues} \u4e2a\u95ee\u9898\uff0cBBox \u547d\u4e2d {bbox_hits}/{bbox_total}\uff0c\u603b Token \u7ea6 {tokens}\u3002",
    },
    "en": {
        "title_suffix": "DraftClaw Report",
        "eyebrow": "Evidence Navigator",
        "language": "Report Language",
        "issues": "Issues",
        "chunks": "Chunks",
        "bbox": "BBox Hits",
        "tokens": "Total Tokens",
        "mode": "Multimodal",
        "toolbar_groups": "Issue Types",
        "toolbar_groups_hint": "Choose a category to sync the navigator and detail panel.",
        "toolbar_nav": "Issue Navigator",
        "toolbar_detail": "Current Issue",
        "prev": "Previous",
        "next": "Next",
        "empty_group": "No issues available in the current category.",
        "empty_detail": "Select an issue to inspect the details.",
        "detail_id": "Issue",
        "detail_description": "Description",
        "detail_evidence": "Evidence",
        "detail_location": "Location",
        "detail_reasoning": "Reasoning",
        "detail_context": "Source Context",
        "detail_bbox": "BBox Match",
        "detail_chunk": "Chunk",
        "detail_source": "Source",
        "detail_score": "Score",
        "detail_page": "Page",
        "detail_coords": "Coords",
        "matched_paragraph": "Matched paragraph",
        "group_meta_default": "Choose a category to inspect issues.",
        "navigator_meta_default": "No issue selected",
        "detail_meta_default": "No issue selected",
        "report_summary": "This report contains {issues} issues, with {bbox_hits}/{bbox_total} bbox matches and about {tokens} total tokens.",
    },
}


def _normalize_language(language: str) -> str:
    lowered = str(language or "").strip().lower()
    return "zh" if lowered.startswith("zh") else "en"


def _color_for_type(type_key: str) -> str:
    key = str(type_key or "").strip()
    if key in TYPE_COLOR_MAP:
        return TYPE_COLOR_MAP[key]
    digest = hashlib.sha1(key.encode("utf-8")).hexdigest()
    return f"#{digest[:6]}"


def _build_issue_groups(report_data: Dict[str, Any]) -> List[Dict[str, Any]]:
    grouped: Dict[str, Dict[str, Any]] = {}
    for index, issue in enumerate(report_data.get("issues", []), start=1):
        if not isinstance(issue, dict):
            continue
        display_type = str(issue.get("type", "") or "Unknown")
        type_key = str(issue.get("type_key", display_type) or display_type)
        group = grouped.setdefault(
            type_key,
            {
                "type_key": type_key,
                "display_label": display_type,
                "color": _color_for_type(type_key),
                "issues": [],
            },
        )
        issue_copy = dict(issue)
        issue_copy.setdefault("id", index)
        group["issues"].append(issue_copy)

    groups = list(grouped.values())
    groups.sort(key=lambda item: (-len(item["issues"]), item["display_label"]))
    for order, group in enumerate(groups, start=1):
        group["sort_order"] = order
        group["issue_count"] = len(group["issues"])
    return groups


def _safe_json_dumps(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False).replace("</", "<\\/")


def render_review_report_html(report_data: Dict[str, Any], document_text: str) -> str:
    language = _normalize_language(report_data.get("report_language", "zh"))
    ui = UI_TEXT[language]
    pdf_name = Path(str(report_data.get("pdf_path", "report.pdf"))).name
    issue_groups = _build_issue_groups(report_data)
    bbox_summary = report_data.get("bbox_summary", {})
    metrics = report_data.get("metrics", {})
    multimodal = report_data.get("multimodal_audit", {})
    language_switch = report_data.get("language_switch", {})

    summary_note = ui["report_summary"].format(
        issues=report_data.get("total_issues", 0),
        bbox_hits=bbox_summary.get("issues_with_bbox", 0),
        bbox_total=bbox_summary.get("total_issues", 0),
        tokens=metrics.get("total_tokens", 0),
    )

    chips = [
        f"{ui['language']}: {language_switch.get('target_language_display', language.upper())}",
        f"{ui['issues']}: {report_data.get('total_issues', 0)}",
        f"{ui['chunks']}: {report_data.get('total_chunks', 0)}",
        f"{ui['bbox']}: {bbox_summary.get('issues_with_bbox', 0)}/{bbox_summary.get('total_issues', 0)}",
        f"{ui['tokens']}: {metrics.get('total_tokens', 0)}",
        f"{ui['mode']}: {multimodal.get('llm_input_mode', 'text-only')}",
    ]

    return f"""<!DOCTYPE html>
<html lang="{'zh-CN' if language == 'zh' else 'en'}">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>{pdf_name} - {ui['title_suffix']}</title>
  <style>
    :root {{
      --canvas:#edf2f8;
      --canvas-soft:#dfe7f1;
      --panel:#f4f7fb;
      --panel-strong:#ffffff;
      --ink:#102033;
      --muted:#5d6e84;
      --line:rgba(37,61,92,.16);
      --shadow:0 24px 48px rgba(17,31,52,.12);
      --radius:24px;
      --accent:#2f6fed;
      --accent-strong:#1847b8;
      --category-bg:linear-gradient(180deg, #eef4fb, #e5eef9);
      --nav-bg:linear-gradient(180deg, #edf3fb, #f8fbff);
      --detail-bg:linear-gradient(180deg, #ffffff, #f3f8ff);
    }}
    * {{ box-sizing:border-box; }}
    body {{ margin:0; min-height:100vh; color:var(--ink); background:radial-gradient(circle at top left, rgba(88,131,212,.16), transparent 28%), radial-gradient(circle at bottom right, rgba(70,112,190,.12), transparent 24%), linear-gradient(180deg, #f6f8fc 0%, var(--canvas) 56%, var(--canvas-soft) 100%); font-family:"Segoe UI","PingFang SC","Microsoft YaHei",sans-serif; }}
    body::before {{ content:""; position:fixed; inset:0; pointer-events:none; background-image:linear-gradient(rgba(142,163,196,.10) 1px, transparent 1px), linear-gradient(90deg, rgba(142,163,196,.10) 1px, transparent 1px); background-size:30px 30px; mask-image:linear-gradient(180deg, rgba(0,0,0,.22), transparent 88%); }}
    h1,h2,h3,p,blockquote,pre {{ margin:0; }}
    .app-shell {{ width:min(1220px, calc(100% - 112px)); margin:0 auto; padding:24px 0 40px; display:block; }}
    .panel {{ border:1px solid rgba(255,255,255,.08); border-radius:var(--radius); background:var(--panel); box-shadow:var(--shadow); overflow:hidden; }}
    .hero {{ padding:22px 26px 18px; border-bottom:1px solid rgba(255,255,255,.08); color:#eff4ff; background:radial-gradient(circle at top left, rgba(109,155,255,.34), transparent 30%), linear-gradient(135deg, #112341, #1b3152 68%, #274672); }}
    .eyebrow {{ margin-bottom:6px; color:rgba(226,236,255,.72); font-size:12px; letter-spacing:.12em; text-transform:uppercase; }}
    .hero-title,.detail-quote,.context-text {{ font-family:"Cambria","Noto Serif SC","Songti SC",serif; letter-spacing:-.02em; }}
    .hero-title {{ font-size:clamp(26px,3vw,34px); line-height:1.24; }}
    .hero-meta {{ margin-top:14px; display:flex; flex-wrap:wrap; gap:10px; }}
    .chip {{ display:inline-flex; align-items:center; padding:7px 12px; border-radius:999px; border:1px solid rgba(255,255,255,.16); background:rgba(255,255,255,.1); color:#ebf2ff; font-size:12px; }}
    .summary-note {{ margin-top:14px; color:rgba(233,241,255,.78); line-height:1.78; font-size:14px; }}
    .explorer {{ display:grid; min-height:calc(100vh - 88px); grid-template-rows:auto auto minmax(0,1fr); }}
    .category-pane,.navigator-pane,.detail-pane {{ min-height:0; display:grid; }}
    .category-pane {{ grid-template-rows:auto auto; border-bottom:1px solid var(--line); background:var(--category-bg); color:#18314d; }}
    .explorer-grid {{ display:grid; grid-template-columns:minmax(320px,.72fr) minmax(0,1.38fr); min-height:0; }}
    .navigator-pane {{ grid-template-rows:auto auto minmax(0,1fr); border-right:1px solid var(--line); background:var(--nav-bg); }}
    .detail-pane {{ grid-template-rows:auto minmax(0,1fr); background:var(--detail-bg); }}
    .toolbar {{ display:flex; align-items:center; justify-content:space-between; gap:14px; padding:14px 18px; border-bottom:1px solid var(--line); background:rgba(255,255,255,.58); }}
    .category-pane .toolbar {{ background:rgba(255,255,255,.66); border-bottom-color:rgba(33,60,98,.10); }}
    .toolbar strong {{ font-size:13px; letter-spacing:.08em; text-transform:uppercase; }}
    .toolbar span {{ color:var(--muted); font-size:12px; }}
    .navigator-actions {{ display:flex; gap:10px; padding:12px 16px; border-bottom:1px solid var(--line); background:rgba(240,245,251,.9); }}
    .nav-button {{ min-width:96px; padding:9px 12px; border-radius:999px; border:1px solid rgba(33,60,98,.18); background:rgba(255,255,255,.94); color:var(--ink); font-size:13px; font-weight:700; cursor:pointer; transition:transform .18s ease, box-shadow .18s ease; }}
    .nav-button:hover {{ transform:translateY(-1px); box-shadow:0 10px 18px rgba(14,28,49,.12); }}
    .nav-button:disabled {{ opacity:.42; cursor:not-allowed; }}
    .navigator-list,.detail-view {{ overflow:auto; }}
    .navigator-list {{ padding:14px; display:grid; gap:10px; align-content:start; }}
    .navigator-card {{ width:100%; padding:15px 16px; border:1px solid rgba(27,54,89,.12); border-left:4px solid var(--accent-color); border-radius:18px; background:rgba(255,255,255,.92); color:var(--ink); text-align:left; cursor:pointer; transition:transform .18s ease, box-shadow .18s ease, background .18s ease; }}
    .navigator-card:hover {{ transform:translateY(-1px); box-shadow:0 12px 22px rgba(18,34,58,.08); }}
    .navigator-card.is-active {{ background:linear-gradient(135deg, color-mix(in srgb, var(--accent-color) 22%, white), rgba(255,255,255,.98)); box-shadow:0 0 0 1px color-mix(in srgb, var(--accent-color) 28%, white), 0 16px 28px rgba(18,34,58,.14); }}
    .navigator-top {{ display:flex; align-items:center; justify-content:space-between; gap:12px; margin-bottom:8px; }}
    .navigator-index {{ display:inline-flex; align-items:center; gap:8px; font-size:12px; font-weight:700; color:var(--muted); }}
    .navigator-index strong {{ display:inline-flex; align-items:center; justify-content:center; min-width:38px; padding:4px 10px; border-radius:999px; background:color-mix(in srgb, var(--accent-color) 16%, white); color:var(--ink); }}
    .navigator-match {{ display:inline-flex; align-items:center; padding:4px 8px; border-radius:999px; border:1px solid rgba(27,54,89,.12); color:var(--muted); font-size:11px; background:rgba(255,255,255,.88); }}
    .navigator-location {{ display:block; font-size:16px; line-height:1.58; font-weight:700; color:#20324a; }}
    .navigator-reason {{ display:block; margin-top:8px; color:var(--muted); font-size:13px; line-height:1.65; }}
    .detail-view {{ padding:16px; background:linear-gradient(180deg, rgba(255,255,255,.44), transparent 60%); }}
    .detail-card {{ display:grid; gap:14px; padding:22px; border-radius:22px; border:1px solid rgba(30,53,88,.12); background:linear-gradient(180deg, rgba(255,255,255,.98), rgba(243,247,253,.96)); box-shadow:0 16px 28px rgba(18,34,58,.09); }}
    .detail-head {{ display:flex; align-items:flex-start; justify-content:space-between; gap:16px; }}
    .detail-title {{ margin-top:6px; font-size:24px; line-height:1.3; font-family:"Cambria","Noto Serif SC","Songti SC",serif; }}
    .detail-badges {{ display:flex; flex-wrap:wrap; gap:8px; }}
    .detail-badge {{ display:inline-flex; align-items:center; padding:6px 10px; border-radius:999px; border:1px solid rgba(30,53,88,.12); background:color-mix(in srgb, var(--accent-color) 12%, white); color:#1b4479; font-size:11px; text-transform:uppercase; }}
    .detail-section {{ padding:16px 18px; border-radius:18px; border:1px solid rgba(27,54,89,.12); background:rgba(255,255,255,.82); }}
    .detail-section.emphasis {{ background:linear-gradient(180deg, color-mix(in srgb, var(--accent-color) 10%, white), rgba(255,255,255,.82)); border-color:color-mix(in srgb, var(--accent-color) 24%, white); }}
    .label {{ display:block; margin-bottom:8px; color:#20324a; font-size:12px; font-weight:800; letter-spacing:.08em; text-transform:uppercase; }}
    .value {{ color:#24364e; line-height:1.8; white-space:pre-wrap; }}
    .subvalue {{ margin-top:10px; padding-top:10px; border-top:1px dashed rgba(27,54,89,.14); color:#52667f; }}
    .detail-quote {{ padding:16px 18px; border-left:4px solid color-mix(in srgb, var(--accent-color) 72%, white); border-radius:0 14px 14px 0; background:rgba(255,255,255,.82); line-height:1.82; white-space:pre-wrap; }}
    .detail-grid {{ display:grid; grid-template-columns:repeat(auto-fit, minmax(180px, 1fr)); gap:10px; }}
    .detail-kv {{ padding:12px 14px; border:1px solid rgba(27,54,89,.12); border-radius:14px; background:rgba(255,255,255,.88); }}
    .detail-kv strong {{ display:block; margin-bottom:6px; font-size:12px; color:#5a6a7f; text-transform:uppercase; }}
    .type-grid {{ padding:12px 14px; display:grid; grid-template-columns:repeat(auto-fit, minmax(140px, 1fr)); gap:8px; background:linear-gradient(180deg, rgba(255,255,255,.58), rgba(255,255,255,.3)); }}
    .type-card {{ position:relative; width:100%; min-height:88px; padding:12px 14px; border-radius:18px; border:1px solid var(--line); border-top:4px solid var(--accent-color); background:linear-gradient(180deg, rgba(255,255,255,.92), rgba(246,249,255,.9)); color:var(--ink); text-align:left; cursor:pointer; transition:transform .18s ease, box-shadow .18s ease, border-color .18s ease, background .18s ease; }}
    .type-card:hover {{ transform:translateY(-1px); box-shadow:0 10px 20px rgba(23,39,63,.08); }}
    .type-card.is-active {{ border-color:color-mix(in srgb, var(--accent-color) 38%, white); transform:translateY(-2px); box-shadow:0 12px 24px rgba(18,34,58,.10), inset 0 0 0 1px rgba(255,255,255,.42); background:linear-gradient(150deg, color-mix(in srgb, var(--accent-color) 10%, white), rgba(255,255,255,.98)); color:#17304d; }}
    .type-card-top {{ display:flex; align-items:flex-start; justify-content:space-between; gap:10px; }}
    .type-card h3 {{ font-size:12px; line-height:1.35; margin-bottom:8px; }}
    .type-card .count {{ font-size:28px; line-height:1; font-weight:700; letter-spacing:-.04em; font-variant-numeric:tabular-nums; }}
    .empty-state {{ padding:24px; color:var(--muted); line-height:1.74; }}
    .context-text {{ font-size:15px; line-height:1.74; white-space:pre-wrap; color:#20324a; }}
    mark {{ background:rgba(37,99,235,.16); color:inherit; padding:.08em .14em; border-radius:4px; }}
    .screenshot-item {{ margin-top:12px; }}
    .screenshot-caption {{ font-size:12px; color:#666; line-height:1.5; word-break:break-all; }}
    @media (max-width:1140px) {{ .app-shell {{ width:min(100%, calc(100% - 48px)); }} .explorer {{ min-height:auto; }} }}
    @media (max-width:900px) {{ .app-shell {{ width:min(100%, calc(100% - 28px)); padding:14px 0 24px; }} .explorer-grid {{ grid-template-columns:1fr; }} .navigator-pane {{ border-right:0; border-bottom:1px solid var(--line); }} }}
  </style>
</head>
<body>
  <main class="app-shell">
    <section class="panel explorer">
      <header class="hero">
        <p class="eyebrow">{ui['eyebrow']}</p>
        <h1 class="hero-title">{pdf_name}</h1>
        <div class="hero-meta">
          {"".join(f'<span class="chip">{chip}</span>' for chip in chips)}
        </div>
        <p class="summary-note">{summary_note}</p>
      </header>
      <section class="category-pane">
        <div class="toolbar"><strong>{ui['toolbar_groups']}</strong><span id="groupMeta">{ui['group_meta_default']}</span></div>
        <section id="typeGrid" class="type-grid"></section>
      </section>
      <div class="explorer-grid">
        <aside class="navigator-pane">
          <div class="toolbar"><strong>{ui['toolbar_nav']}</strong><span id="navigatorMeta">{ui['navigator_meta_default']}</span></div>
          <div class="navigator-actions">
            <button id="prevError" class="nav-button" type="button">{ui['prev']}</button>
            <button id="nextError" class="nav-button" type="button">{ui['next']}</button>
          </div>
          <div id="errorNavigator" class="navigator-list"></div>
        </aside>
        <section class="detail-pane">
          <div class="toolbar"><strong>{ui['toolbar_detail']}</strong><span id="detailMeta">{ui['detail_meta_default']}</span></div>
          <div id="errorDetail" class="detail-view"></div>
        </section>
      </div>
    </section>
  </main>
  <script>
    const uiText = {_safe_json_dumps(ui)};
    const issueGroups = {_safe_json_dumps(issue_groups)};
    const documentText = {_safe_json_dumps(document_text)};
    const documentParagraphs = splitParagraphs(documentText);
    let activeGroupIndex = issueGroups.length ? 0 : -1;
    let activeIssueIndex = issueGroups.length && issueGroups[0].issues.length ? 0 : -1;

    function escapeHtml(value) {{
      return String(value).replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;").replace(/"/g, "&quot;").replace(/'/g, "&#39;");
    }}
    function escapeRegExp(value) {{
      return String(value).replace(/[.*+?^${{}}()|[\\]\\\\]/g, "\\\\$&");
    }}
    function splitParagraphs(value) {{
      return String(value).split(/\\n\\s*\\n+/).map((part) => part.trim()).filter(Boolean);
    }}
    function toTextList(value) {{
      if (Array.isArray(value)) {{
        return value.map((item) => String(item || "").trim()).filter(Boolean);
      }}
      const text = String(value || "").trim();
      return text ? [text] : [];
    }}
    function fieldText(value, separator = "\\n") {{
      return toTextList(value).join(separator);
    }}
    function issueLocationText(issue) {{
      return fieldText(issue.location_display || issue.location || issue.location_original);
    }}
    function issueEvidenceText(issue) {{
      return fieldText(issue.evidence_display || issue.evidence || issue.evidence_original);
    }}
    function normalizeForMatch(value) {{
      return String(value || "").toLowerCase().replace(/[\\s\\u3000]+/g, " ").replace(/[^\\p{{L}}\\p{{N}} ]+/gu, " ").replace(/\\s+/g, " ").trim();
    }}
    function tokenize(value) {{
      const normalized = normalizeForMatch(value);
      return normalized ? Array.from(new Set(normalized.split(" ").filter((token) => token.length >= 2))) : [];
    }}
    function summarizeText(value, limit = 72) {{
      const text = String(value || "").trim();
      return text.length <= limit ? text : `${{text.slice(0, limit - 1)}}…`;
    }}
    function currentGroup() {{
      return issueGroups[activeGroupIndex] || null;
    }}
    function currentIssues() {{
      const group = currentGroup();
      return group ? group.issues : [];
    }}
    function currentIssue() {{
      const issues = currentIssues();
      return activeIssueIndex >= 0 && activeIssueIndex < issues.length ? issues[activeIssueIndex] : null;
    }}
    function scoreParagraph(paragraph, phrases) {{
      const normalizedParagraph = normalizeForMatch(paragraph);
      let score = 0;
      for (const phrase of phrases) {{
        const normalizedPhrase = normalizeForMatch(phrase);
        if (!normalizedPhrase) continue;
        if (normalizedParagraph.includes(normalizedPhrase)) score += 220;
        const paragraphTokens = new Set(tokenize(paragraph));
        score += tokenize(phrase).filter((token) => paragraphTokens.has(token)).length * 16;
      }}
      return score;
    }}
    function buildMatchPhrases(issue) {{
      const phrases = [];
      const keys = ["location_original", "evidence_original", "location", "evidence"];
      for (const key of keys) {{
        const value = String(issue[key] || "").trim();
        if (!value) continue;
        phrases.push(value);
        value.split(/[。！？!?;；:\\n]+/).map((part) => part.trim()).filter((part) => part.length >= 6).forEach((part) => phrases.push(part));
      }}
      return Array.from(new Set(phrases)).sort((left, right) => right.length - left.length);
    }}
    function findBestContext(issue) {{
      const phrases = buildMatchPhrases(issue);
      let best = null;
      documentParagraphs.forEach((paragraph, index) => {{
        const score = scoreParagraph(paragraph, phrases);
        if (!best || score > best.score) best = {{ index, score, paragraph }};
      }});
      return best && best.score > 0 ? best : null;
    }}
    function highlightParagraph(paragraph, issue) {{
      const phrases = buildMatchPhrases(issue).slice(0, 4);
      if (!phrases.length) return escapeHtml(paragraph);
      const pattern = new RegExp(phrases.map((phrase) => escapeRegExp(phrase).replace(/\\s+/g, "\\\\s+")).join("|"), "gi");
      let html = "";
      let lastIndex = 0;
      const source = String(paragraph);
      source.replace(pattern, (match, offset) => {{
        html += escapeHtml(source.slice(lastIndex, offset));
        html += `<mark>${{escapeHtml(match)}}</mark>`;
        lastIndex = offset + match.length;
        return match;
      }});
      html += escapeHtml(source.slice(lastIndex));
      return html;
    }}
    function renderTextWithOriginal(label, translated, original) {{
      const translatedBlock = translated ? `<div class="value">${{escapeHtml(translated)}}</div>` : `<div class="value"></div>`;
      const originalText = String(original || "").trim();
      const translatedText = String(translated || "").trim();
      const originalBlock = originalText && originalText !== translatedText
        ? `<div class="subvalue">${{escapeHtml(originalText)}}</div>`
        : "";
      return `<section class="detail-section"><span class="label">${{escapeHtml(label)}}</span>${{translatedBlock}}${{originalBlock}}</section>`;
    }}
    function renderEvidenceWithScreenshot(label, text, originalText, screenshots, screenshotKind) {{
      const textBlock = text ? `<div class="value">${{escapeHtml(text)}}</div>` : `<div class="value"></div>`;
      const normalizedOriginal = fieldText(originalText);
      const normalizedText = fieldText(text);
      const originalBlock = normalizedOriginal && normalizedOriginal !== normalizedText
        ? `<div class="subvalue">${{escapeHtml(normalizedOriginal)}}</div>`
        : "";
      const relevantScreenshots = (screenshots || []).filter(s => s && s.kind === screenshotKind);
      let screenshotHtml = "";
      for (const ss of relevantScreenshots) {{
        const path = ss.local_path || "";
        if (!path) continue;
        const page = ss.page || "N/A";
        const matched = ss.matched_text ? ss.matched_text.substring(0, 150) : "";
        const escapedPath = path.replace(/\\/g, "/");
        screenshotHtml += `<div class="screenshot-item" style="margin-top:10px;">
          <img src="${{escapedPath}}" alt="${{screenshotKind}} screenshot" style="max-width:100%;border:2px solid #4a90d9;border-radius:10px;" onerror="this.outerHTML='<p style=\\'color:#c00\\'>[Screenshot unavailable: ${{escapedPath}}]</p>'">
          <p style="margin:6px 0 0;font-size:12px;color:#666;">${{screenshotKind}} | page ${{page}}${{matched ? " | matched: " + matched.slice(0, 80) + "..." : ""}}</p>
        </div>`;
      }}
      return `<section class="detail-section"><span class="label">${{escapeHtml(label)}}</span>${{textBlock}}${{originalBlock}}${{screenshotHtml}}</section>`;
    }}
    function renderTypeCards() {{
      const host = document.getElementById("typeGrid");
      const groupMeta = document.getElementById("groupMeta");
      const group = currentGroup();
      groupMeta.textContent = group
        ? `${{group.display_label}} | ${{group.issue_count}}`
        : uiText.group_meta_default;
      host.innerHTML = issueGroups.map((groupItem, index) => `
        <button class="type-card ${{index === activeGroupIndex ? "is-active" : ""}}" data-group-index="${{index}}" style="--accent-color:${{groupItem.color}}">
          <div class="type-card-top"><h3>${{escapeHtml(groupItem.display_label)}}</h3></div>
          <div class="count">${{groupItem.issue_count}}</div>
        </button>`).join("");
      host.querySelectorAll(".type-card").forEach((button) => {{
        button.addEventListener("click", () => selectGroup(Number(button.dataset.groupIndex)));
      }});
    }}
    function renderNavigator() {{
      const host = document.getElementById("errorNavigator");
      const meta = document.getElementById("navigatorMeta");
      const prevButton = document.getElementById("prevError");
      const nextButton = document.getElementById("nextError");
      const group = currentGroup();
      const issues = currentIssues();
      if (!group || !issues.length) {{
        host.innerHTML = `<div class="empty-state">${{escapeHtml(uiText.empty_group)}}</div>`;
        meta.textContent = uiText.navigator_meta_default;
        prevButton.disabled = true;
        nextButton.disabled = true;
        return;
      }}
      meta.textContent = `#${{issues[activeIssueIndex].id}} / ${{issues.length}}`;
      prevButton.disabled = activeIssueIndex <= 0;
      nextButton.disabled = activeIssueIndex >= issues.length - 1;
      host.innerHTML = issues.map((issue, index) => {{
        const bbox = issue.best_bbox_match || {{}};
        const matchLabel = bbox.page ? `${{uiText.detail_page}} ${{bbox.page}}` : uiText.detail_bbox;
        return `<button class="navigator-card ${{index === activeIssueIndex ? "is-active" : ""}}" data-issue-index="${{index}}" style="--accent-color:${{group.color}}">
          <div class="navigator-top"><span class="navigator-index"><strong>#${{issue.id}}</strong>${{escapeHtml(issue.severity || "")}}</span><span class="navigator-match">${{escapeHtml(matchLabel)}}</span></div>
          <span class="navigator-location">${{escapeHtml(summarizeText(issueLocationText(issue) || issueEvidenceText(issue) || "", 64))}}</span>
          <span class="navigator-reason">${{escapeHtml(summarizeText(issue.description || "", 108))}}</span>
        </button>`;
      }}).join("");
      host.querySelectorAll(".navigator-card").forEach((button) => {{
        button.addEventListener("click", () => selectIssue(Number(button.dataset.issueIndex)));
      }});
    }}
    function renderDetail() {{
      const host = document.getElementById("errorDetail");
      const meta = document.getElementById("detailMeta");
      const group = currentGroup();
      const issue = currentIssue();
      if (!group || !issue) {{
        host.innerHTML = `<div class="empty-state">${{escapeHtml(uiText.empty_detail)}}</div>`;
        meta.textContent = uiText.detail_meta_default;
        return;
      }}
      meta.textContent = `${{uiText.detail_id}} #${{issue.id}}`;
      const bbox = issue.best_bbox_match || {{}};
      const context = findBestContext(issue);
      const contextHtml = context
        ? `<section class="detail-section"><span class="label">${{escapeHtml(uiText.detail_context)}}</span><div class="value"><p class="context-text">${{highlightParagraph(context.paragraph, issue)}}</p></div></section>`
        : "";
      host.innerHTML = `<div class="detail-card" style="--accent-color:${{group.color}}">
        <div class="detail-head">
          <div>
            <p class="eyebrow">${{escapeHtml(uiText.detail_id)}}</p>
            <h3 class="detail-title">#${{issue.id}} - ${{escapeHtml(group.display_label)}}</h3>
          </div>
          <div class="detail-badges">
            <span class="detail-badge">${{escapeHtml(issue.severity || "")}}</span>
            <span class="detail-badge">${{escapeHtml(`chunk ${{issue.chunk_id ?? "N/A"}}`)}}</span>
          </div>
        </div>
        ${{renderTextWithOriginal(uiText.detail_description, issue.description, issue.description_original)}}
        ${{renderEvidenceWithScreenshot(uiText.detail_evidence, issueEvidenceText(issue), issue.evidence_original, issue.vision_screenshots || issue.bbox_debug_screenshots || [], "evidence")}}
        ${{renderEvidenceWithScreenshot(uiText.detail_location, issueLocationText(issue), issue.location_original, issue.vision_screenshots || issue.bbox_debug_screenshots || [], "location")}}
        ${{renderTextWithOriginal(uiText.detail_reasoning, issue.reasoning, issue.reasoning_original)}}
        <section class="detail-section emphasis">
          <span class="label">${{escapeHtml(uiText.detail_bbox)}}</span>
          <div class="detail-grid">
            <div class="detail-kv"><strong>${{escapeHtml(uiText.detail_page)}}</strong><span>${{escapeHtml(bbox.page ?? "N/A")}}</span></div>
            <div class="detail-kv"><strong>${{escapeHtml(uiText.detail_source)}}</strong><span>${{escapeHtml(bbox.source || "N/A")}}</span></div>
            <div class="detail-kv"><strong>${{escapeHtml(uiText.detail_score)}}</strong><span>${{escapeHtml(bbox.score ?? "N/A")}}</span></div>
            <div class="detail-kv"><strong>${{escapeHtml(uiText.detail_coords)}}</strong><span>${{escapeHtml(JSON.stringify(bbox.bbox || []))}}</span></div>
          </div>
        </section>
        ${{contextHtml}}
      </div>`;
    }}
    function renderAll() {{
      renderTypeCards();
      renderNavigator();
      renderDetail();
    }}
    function selectGroup(index) {{
      activeGroupIndex = index;
      activeIssueIndex = currentIssues().length ? 0 : -1;
      renderAll();
    }}
    function selectIssue(index) {{
      activeIssueIndex = index;
      renderDetail();
      renderNavigator();
    }}
    function navigate(delta) {{
      const issues = currentIssues();
      if (!issues.length) return;
      const nextIndex = Math.max(0, Math.min(issues.length - 1, activeIssueIndex + delta));
      if (nextIndex === activeIssueIndex) return;
      selectIssue(nextIndex);
    }}
    document.getElementById("prevError").addEventListener("click", () => navigate(-1));
    document.getElementById("nextError").addEventListener("click", () => navigate(1));
    renderAll();
  </script>
</body>
</html>
"""
