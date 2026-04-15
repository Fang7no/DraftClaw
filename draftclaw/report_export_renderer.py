"""
Self-contained interactive report export for DraftClaw.
"""

from __future__ import annotations

import json
from html import escape
from pathlib import Path
from typing import Any, Dict, List

from issue_review import get_issue_review_decision
from pdf_page_renderer import build_embedded_page_manifest


UI_TEXT = {
    "zh": {
        "title_suffix": "检测报告",
        "pdf_title": "PDF 对照",
        "issues_title": "问题列表",
        "search_placeholder": "搜索问题",
        "all_issues": "全部",
        "confirmed_issues": "确认问题",
        "no_issues": "当前没有可展示的问题。",
        "loading_pdf": "正在准备 PDF 页图",
        "page": "页",
        "zoom_in": "放大",
        "zoom_out": "缩小",
        "location": "错误位置",
        "evidence": "证据位置",
        "bbox_ready": "已定位 bbox",
        "bbox_missing": "未定位 bbox",
        "decision_keep": "已确认",
        "decision_review": "待复核",
        "decision_unchecked": "未复核",
        "decision_drop": "已剔除",
        "chunk": "Chunk",
        "empty_value": "暂无",
        "issue_count": "个问题",
    },
    "en": {
        "title_suffix": "Review Report",
        "pdf_title": "PDF Reference",
        "issues_title": "Issues",
        "search_placeholder": "Search issues",
        "all_issues": "All",
        "confirmed_issues": "Confirmed",
        "no_issues": "No issues to display.",
        "loading_pdf": "Preparing rendered pages",
        "page": "Page",
        "zoom_in": "Zoom In",
        "zoom_out": "Zoom Out",
        "description": "Description",
        "reasoning": "Reasoning",
        "location": "Issue Location",
        "evidence": "Evidence",
        "bbox_ready": "bbox ready",
        "bbox_missing": "bbox missing",
        "decision_keep": "Confirmed",
        "decision_review": "Needs review",
        "decision_unchecked": "Unchecked",
        "decision_drop": "Dropped",
        "chunk": "Chunk",
        "empty_value": "Empty",
        "issue_count": "issues",
    },
}


def _safe_json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False).replace("</", "<\\/")


def _normalize_language(language: str) -> str:
    lowered = str(language or "").strip().lower()
    return "zh" if lowered.startswith("zh") else "en"


def _normalize_text(value: Any) -> str:
    if isinstance(value, list):
        items = [str(item or "").strip() for item in value]
        return "\n".join(item for item in items if item)
    return str(value or "").strip()


def _prepare_issues(report_data: Dict[str, Any]) -> List[Dict[str, Any]]:
    prepared: List[Dict[str, Any]] = []
    for index, issue in enumerate(report_data.get("issues", []), start=1):
        if not isinstance(issue, dict):
            continue
        decision = get_issue_review_decision(issue)
        if decision == "drop":
            continue
        issue_copy = dict(issue)
        issue_copy["client_id"] = issue_copy.get("client_id") or f"issue-{index}"
        issue_copy["evidence"] = _normalize_text(issue_copy.get("evidence"))
        issue_copy["location"] = _normalize_text(issue_copy.get("location"))
        issue_copy["evidence_display"] = _normalize_text(issue_copy.get("evidence_display"))
        issue_copy["location_display"] = _normalize_text(issue_copy.get("location_display"))
        issue_copy["evidence_original"] = _normalize_text(issue_copy.get("evidence_original"))
        issue_copy["location_original"] = _normalize_text(issue_copy.get("location_original"))
        issue_copy["description"] = _normalize_text(issue_copy.get("description"))
        issue_copy["reasoning"] = _normalize_text(issue_copy.get("reasoning"))
        prepared.append(issue_copy)
    return prepared


def render_export_report_html(report_data: Dict[str, Any], pdf_path: str) -> str:
    language = _normalize_language(report_data.get("report_language", "zh"))
    ui = UI_TEXT[language]
    pdf_file = Path(pdf_path)
    pdf_name = pdf_file.name
    issues = _prepare_issues(report_data)
    pages_manifest = build_embedded_page_manifest(pdf_path)

    payload = {
        "language": language,
        "pdfName": pdf_name,
        "issues": issues,
        "ui": ui,
        "pages": pages_manifest.get("pages", []),
        "page_count": pages_manifest.get("page_count", 0),
        "bbox_debug_summary": report_data.get("bbox_debug_summary", {}),
    }

    title = f"{pdf_name} - {ui['title_suffix']}"
    subtitle = f"{len(issues)} {ui['issue_count']}"

    return f"""<!DOCTYPE html>
<html lang="{'zh-CN' if language == 'zh' else 'en'}">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>{escape(title)}</title>
  <style>
    @import url("https://fonts.googleapis.com/css2?family=Fira+Code:wght@400;500;600&family=Fira+Sans:wght@400;500;600;700&display=swap");
    :root {{
      --primary:#2457d6;
      --primary-dark:#153c97;
      --bg:#f4f7fb;
      --panel:#ffffff;
      --panel-soft:#f8fbff;
      --text:#102033;
      --muted:#5d6e84;
      --border:rgba(37,61,92,.20);
      --border-strong:rgba(37,61,92,.26);
      --shadow:0 18px 42px rgba(20,45,88,.10);
      --success:#1f9d6a;
      --warning:#d18a1c;
      --danger:#d34a4a;
      --location-color:rgba(66,135,255,.12);
      --location-border:#4287f5;
      --evidence-color:rgba(255,87,87,.10);
      --evidence-border:#ff5757;
      --workspace-height:calc(100vh - 132px);
      --panel-mobile-height:420px;
    }}
    * {{ box-sizing:border-box; }}
    body {{
      margin:0;
      min-height:100vh;
      font-family:"Fira Sans","PingFang SC","Microsoft YaHei",sans-serif;
      color:var(--text);
      background:linear-gradient(180deg, #f9fbfe 0%, #f3f7fb 100%);
    }}
    button,input {{ font:inherit; }}
    button {{ cursor:pointer; }}
    .shell {{
      min-height:100vh;
      padding:18px;
      display:flex;
      flex-direction:column;
      gap:14px;
    }}
    .header,
    .panel {{
      background:var(--panel);
      border:1px solid var(--border-strong);
      border-radius:16px;
      box-shadow:var(--shadow);
    }}
    .header {{
      padding:10px 14px;
      display:flex;
      align-items:center;
      justify-content:space-between;
      gap:12px;
    }}
    .header h1 {{ margin:0 0 2px; font-size:16px; }}
    .header p {{ margin:0; color:var(--muted); font-size:12px; }}
    .chip-row {{ display:flex; flex-wrap:wrap; gap:8px; }}
    .chip {{
      padding:6px 10px;
      border-radius:999px;
      border:1px solid var(--border);
      background:var(--panel-soft);
      color:var(--muted);
      font-size:12px;
      font-weight:600;
    }}
    .workspace {{
      display:flex;
      align-items:stretch;
      gap:0;
      height:var(--workspace-height);
      min-height:620px;
    }}
    .workspace-divider {{
      position:relative;
      flex:0 0 16px;
      cursor:col-resize;
    }}
    .workspace-divider::before {{
      content:"";
      position:absolute;
      top:18px;
      bottom:18px;
      left:5px;
      right:5px;
      border-radius:999px;
      background:rgba(47,111,237,.14);
      transition:background .2s ease;
    }}
    .workspace-divider:hover::before,
    .workspace-divider.active::before {{
      background:rgba(47,111,237,.34);
    }}
    .panel {{
      min-height:0;
      display:flex;
      flex-direction:column;
      overflow:hidden;
    }}
    .panel--pdf,
    .panel--issues {{
      flex:0 0 calc(50% - 8px);
      min-width:0;
    }}
    .panel-header {{
      display:flex;
      align-items:center;
      justify-content:space-between;
      gap:12px;
      padding:10px 12px;
      border-bottom:1px solid var(--border);
      background:#f9fbfe;
    }}
    .panel-header strong {{ font-size:13px; }}
    .panel-body {{
      flex:1;
      display:flex;
      flex-direction:column;
      min-height:0;
      padding:14px;
      overflow:hidden;
    }}
    .panel-body--pdf {{
      display:flex;
      flex-direction:column;
      gap:12px;
      background:#59606f;
    }}
    .legend,
    .issue-stats,
    .chip-group,
    .issue-card-top,
    .issue-card-foot {{
      display:flex;
      align-items:center;
      gap:8px;
    }}
    .legend-chip,
    .type-pill,
    .severity-pill,
    .decision-pill {{
      padding:5px 10px;
      border-radius:999px;
      font-size:11px;
      font-weight:600;
    }}
    .legend-chip--location {{ background:var(--location-color); color:var(--location-border); }}
    .legend-chip--evidence {{ background:var(--evidence-color); color:var(--evidence-border); }}
    .pdf-toolbar {{
      position:sticky;
      top:0;
      z-index:5;
      display:flex;
      align-items:center;
      gap:8px;
      flex-wrap:wrap;
      padding:10px 12px;
      border:1px solid rgba(255,255,255,.14);
      border-radius:12px;
      background:rgba(255,255,255,.94);
    }}
    .pdf-toolbar button,
    .pdf-toolbar input,
    .chip-btn {{
      border:1px solid var(--border);
      border-radius:8px;
      background:#fff;
    }}
    .pdf-toolbar button {{ padding:7px 10px; }}
    .pdf-toolbar button.active {{
      border-color:rgba(47,111,237,.42);
      background:rgba(47,111,237,.10);
      color:var(--primary-dark);
    }}
    .pdf-toolbar input {{ width:68px; padding:6px 8px; }}
    .pdf-toolbar label {{
      display:flex;
      align-items:center;
      gap:8px;
      color:var(--muted);
      font-size:13px;
    }}
    .panel-body--pdf > .pdf-toolbar:first-child:not(.pdf-toolbar--compact) {{ display:none; }}
    .pdf-toolbar--compact {{
      display:flex;
      align-items:center;
      gap:10px;
      flex-wrap:nowrap;
      padding:8px 10px;
      overflow-x:auto;
      overflow-y:hidden;
      scrollbar-width:thin;
    }}
    .pdf-mini-group {{
      display:inline-flex;
      align-items:center;
      gap:6px;
      padding:2px;
      border:1px solid rgba(37,61,92,.12);
      border-radius:999px;
      background:rgba(255,255,255,.90);
    }}
    .pdf-mini-btn {{
      min-width:22px;
      height:24px;
      padding:0 6px;
      border:1px solid var(--border);
      border-radius:999px;
      background:#fff;
      font-size:11px;
      line-height:1;
      color:#111;
      font-weight:700;
    }}
    .pdf-mini-value {{
      min-width:60px;
      text-align:center;
      font-size:12px;
      color:#111;
      font-weight:700;
    }}
    .pdf-focus-group {{
      display:grid;
      grid-template-columns:22px 52px 22px;
      align-items:center;
      column-gap:8px;
      row-gap:4px;
      margin-left:0;
      padding:6px 10px;
      border:1px solid transparent;
      border-radius:999px;
      background:rgba(255,255,255,.78);
      flex:0 0 auto;
    }}
    .pdf-focus-group.active {{
      border-color:rgba(47,111,237,.22);
      background:rgba(47,111,237,.08);
    }}
    .pdf-focus-label,
    .pdf-focus-counter {{
      font-size:11px;
      color:#111;
      font-weight:700;
      white-space:nowrap;
    }}
    .pdf-focus-label {{
      grid-column:1 / -1;
      min-width:0;
    }}
    .pdf-focus-counter {{
      min-width:52px;
      text-align:center;
    }}
    .pdf-scroll {{
      flex:1;
      min-height:0;
      overflow:auto;
      padding-bottom:20px;
    }}
    .pdf-stack {{
      display:flex;
      flex-direction:column;
      align-items:center;
      gap:18px;
    }}
    .pdf-page {{
      display:flex;
      flex-direction:column;
      align-items:center;
      gap:8px;
    }}
    .pdf-page-label {{
      padding:4px 10px;
      border-radius:999px;
      background:rgba(255,255,255,.12);
      color:#fff;
      font-size:12px;
    }}
    .pdf-page-shell {{
      position:relative;
      background:#fff;
      box-shadow:0 10px 26px rgba(0,0,0,.24);
    }}
    .pdf-page-image {{
      display:block;
      width:100%;
      height:100%;
      user-select:none;
      pointer-events:none;
    }}
    .pdf-overlay {{
      position:absolute;
      border:2px solid;
      border-radius:8px;
      pointer-events:none;
      transition:box-shadow .18s ease, transform .18s ease, border-width .18s ease;
    }}
    .pdf-overlay span {{
      position:absolute;
      top:-24px;
      left:0;
      padding:3px 8px;
      border-radius:999px;
      color:#fff;
      font-size:11px;
      font-weight:600;
      white-space:nowrap;
    }}
    .pdf-overlay--location {{ border-color:var(--location-border); background:var(--location-color); }}
    .pdf-overlay--location span {{ background:var(--location-border); }}
    .pdf-overlay--evidence {{ border-color:var(--evidence-border); background:var(--evidence-color); }}
    .pdf-overlay--evidence span {{ background:var(--evidence-border); }}
    .pdf-overlay--active {{
      border-width:3px;
      box-shadow:0 0 0 3px rgba(255,255,255,.92), 0 0 0 6px rgba(33,66,116,.18);
      transform:translateZ(0);
      z-index:2;
    }}
    .issue-toolbar {{ display:grid; gap:12px; margin-bottom:14px; }}
    .chip-group {{ flex-wrap:wrap; }}
    .chip-btn {{
      padding:6px 12px;
      color:var(--muted);
      transition:all .2s;
    }}
    .chip-btn.current {{
      border-color:rgba(47,111,237,.24);
      background:rgba(47,111,237,.08);
      color:var(--primary-dark);
    }}
    .chip-btn.active {{
      color:#fff;
      background:var(--primary);
      border-color:var(--primary);
    }}
    .issues-scroll {{
      flex:1;
      min-height:0;
      overflow:auto;
      padding-right:4px;
      overscroll-behavior:contain;
      scrollbar-gutter:stable both-edges;
    }}
    .issue-list {{
      display:grid;
      gap:12px;
      scroll-snap-type:y proximity;
    }}
    .issue-card {{
      width:100%;
      padding:16px;
      border:1px solid var(--border);
      border-radius:12px;
      background:var(--panel-soft);
      text-align:left;
      scroll-snap-align:start;
      transition:border-color .2s, box-shadow .2s, transform .2s;
    }}
    .issue-card:hover {{ transform:translateY(-1px); }}
    .issue-card.active {{
      border-color:var(--primary);
      box-shadow:0 0 0 3px rgba(47,111,237,.10);
    }}
    .issue-card small {{
      color:var(--muted);
    }}
    .issue-card-top,
    .issue-card-foot {{
      justify-content:space-between;
      gap:10px;
    }}
    .issue-badges {{
      display:flex;
      flex-wrap:wrap;
      gap:8px;
    }}
    .type-pill {{ background:rgba(47,111,237,.10); color:var(--primary-dark); }}
    .severity-pill--high,
    .decision-pill--drop {{ background:rgba(211,74,74,.10); color:var(--danger); }}
    .severity-pill--medium,
    .decision-pill--review,
    .decision-pill--unchecked {{ background:rgba(209,138,28,.10); color:var(--warning); }}
    .severity-pill--low,
    .decision-pill--keep {{ background:rgba(31,157,106,.10); color:var(--success); }}
    .issue-block {{
      padding:12px;
      border-radius:10px;
      background:#fff;
      border:1px solid rgba(47,111,237,.08);
      min-height:0;
    }}
    .issue-block span {{
      display:inline-block;
      margin-bottom:6px;
      font-size:11px;
      font-weight:600;
      color:var(--muted);
    }}
    .issue-block p {{
      margin:0;
      font-size:13px;
      line-height:1.65;
      white-space:pre-wrap;
      max-height:10.5em;
      overflow:auto;
      padding-right:4px;
    }}
    .is-resizing,
    .is-resizing * {{
      cursor:col-resize !important;
      user-select:none;
    }}
    @media (max-width: 980px) {{
      .workspace {{
        flex-direction:column;
        height:auto;
      }}
      .workspace-divider {{
        display:none;
      }}
      .header {{
        flex-direction:column;
        align-items:flex-start;
      }}
      .panel {{
        height:var(--panel-mobile-height);
      }}
      .panel--pdf,
      .panel--issues {{
        flex:1 1 auto;
      }}
    }}
  </style>
</head>
<body>
  <div class="shell">
    <header class="header">
      <div>
        <h1>{escape(pdf_name)}</h1>
        <p>{escape(subtitle)}</p>
      </div>
      <div class="chip-row">
        <span class="chip">{escape(ui["issues_title"])}: {len(issues)}</span>
        <span class="chip">{escape(ui["confirmed_issues"])}</span>
      </div>
    </header>

    <div id="workspace" class="workspace">
      <section id="pdfPanel" class="panel panel--pdf">
        <div class="panel-header">
          <strong>{escape(ui["pdf_title"])}</strong>
          <div class="legend">
            <span class="legend-chip legend-chip--location">{escape(ui["location"])}</span>
            <span class="legend-chip legend-chip--evidence">{escape(ui["evidence"])}</span>
          </div>
        </div>
        <div class="panel-body panel-body--pdf">
          <div class="pdf-toolbar">
            <button type="button" id="prevPage">-</button>
            <label>
              <span>{escape(ui["page"])}</span>
              <input id="pageInput" type="number" min="1" value="1">
            </label>
            <span id="pageCount">/ {int(pages_manifest.get("page_count", 0) or 0)}</span>
            <button type="button" id="nextPage">+</button>
            <button type="button" id="zoomOut">{escape(ui["zoom_out"])}</button>
            <span id="zoomValue">78%</span>
            <button type="button" id="zoomIn">{escape(ui["zoom_in"])}</button>
          </div>
          <div class="pdf-toolbar pdf-toolbar--compact">
            <div class="pdf-mini-group">
              <button type="button" id="prevPageCompact" class="pdf-mini-btn">-</button>
              <span id="pageCompactValue" class="pdf-mini-value">1 / {int(pages_manifest.get("page_count", 0) or 0)}</span>
              <button type="button" id="nextPageCompact" class="pdf-mini-btn">+</button>
            </div>
            <div class="pdf-mini-group">
              <button type="button" id="zoomOutCompact" class="pdf-mini-btn">-</button>
              <span id="zoomCompactValue" class="pdf-mini-value">78%</span>
              <button type="button" id="zoomInCompact" class="pdf-mini-btn">+</button>
            </div>
            <div id="locationFocusGroup" class="pdf-focus-group">
              <span class="pdf-focus-label">Issue Location</span>
              <button type="button" id="locationPrev" class="pdf-mini-btn">&lt;</button>
              <span id="locationCounter" class="pdf-focus-counter">-</span>
              <button type="button" id="locationNext" class="pdf-mini-btn">&gt;</button>
            </div>
            <div id="evidenceFocusGroup" class="pdf-focus-group">
              <span class="pdf-focus-label">Issue Evidence</span>
              <button type="button" id="evidencePrev" class="pdf-mini-btn">&lt;</button>
              <span id="evidenceCounter" class="pdf-focus-counter">-</span>
              <button type="button" id="evidenceNext" class="pdf-mini-btn">&gt;</button>
            </div>
          </div>
          <div id="pdfScroll" class="pdf-scroll">
            <div id="pdfStack" class="pdf-stack"></div>
          </div>
        </div>
      </section>

      <div
        id="workspaceDivider"
        class="workspace-divider"
        role="separator"
        aria-orientation="vertical"
        aria-label="Resize PDF and issues panels"
      ></div>

      <section id="issuesPanel" class="panel panel--issues">
        <div class="panel-header">
          <strong>{escape(ui["issues_title"])}</strong>
          <div class="issue-stats">
            <span>{len(issues)} {escape(ui["issue_count"])}</span>
          </div>
        </div>
        <div class="panel-body">
          <div class="issue-toolbar">
            <div id="typeChips" class="chip-group"></div>
          </div>
          <div class="issues-scroll">
            <div id="issueList" class="issue-list"></div>
          </div>
        </div>
      </section>
    </div>
  </div>

  <script>
    const REPORT = {_safe_json(payload)};
    const state = {{
      issues: REPORT.issues.slice(),
      pages: REPORT.pages.slice(),
      selectedType: "all",
      selectedIssueId: REPORT.issues[0]?.client_id || "",
      pdfFocusKind: "location",
      pdfFocusIndex: 0,
      splitRatio: 0.5,
      isResizing: false,
      zoom: 0.78,
      currentPage: 1,
      pageSections: new Map(),
      pageShells: new Map(),
      pageSizes: new Map(),
    }};

    const ui = REPORT.ui;
    const pdfScroll = document.getElementById("pdfScroll");
    const pdfStack = document.getElementById("pdfStack");
    const issueList = document.getElementById("issueList");
    const typeChips = document.getElementById("typeChips");
    const workspace = document.getElementById("workspace");
    const pdfPanel = document.getElementById("pdfPanel");
    const issuesPanel = document.getElementById("issuesPanel");
    const workspaceDivider = document.getElementById("workspaceDivider");
    const pageInput = document.getElementById("pageInput");
    const pageCount = document.getElementById("pageCount");
    const zoomValue = document.getElementById("zoomValue");
    const prevPage = document.getElementById("prevPage");
    const nextPage = document.getElementById("nextPage");
    const zoomIn = document.getElementById("zoomIn");
    const zoomOut = document.getElementById("zoomOut");
    const pageCompactValue = document.getElementById("pageCompactValue");
    const zoomCompactValue = document.getElementById("zoomCompactValue");
    const prevPageCompact = document.getElementById("prevPageCompact");
    const nextPageCompact = document.getElementById("nextPageCompact");
    const zoomInCompact = document.getElementById("zoomInCompact");
    const zoomOutCompact = document.getElementById("zoomOutCompact");
    const locationFocusGroup = document.getElementById("locationFocusGroup");
    const evidenceFocusGroup = document.getElementById("evidenceFocusGroup");
    const locationCounter = document.getElementById("locationCounter");
    const evidenceCounter = document.getElementById("evidenceCounter");
    const locationPrev = document.getElementById("locationPrev");
    const locationNext = document.getElementById("locationNext");
    const evidencePrev = document.getElementById("evidencePrev");
    const evidenceNext = document.getElementById("evidenceNext");

    function asArray(value) {{
      return Array.isArray(value) ? value : [];
    }}

    function safeLower(value) {{
      return String(value || "").trim().toLowerCase();
    }}

    function clamp(value, min, max) {{
      return Math.min(Math.max(value, min), max);
    }}

    function isStackedLayout() {{
      return window.innerWidth <= 980;
    }}

    function applySplitRatio() {{
      if (!workspace || !pdfPanel || !issuesPanel) return;
      if (isStackedLayout()) {{
        pdfPanel.style.flex = "";
        issuesPanel.style.flex = "";
        return;
      }}
      state.splitRatio = clamp(Number(state.splitRatio || 0.5), 0.24, 0.76);
      const leftPercent = (state.splitRatio * 100).toFixed(2);
      const rightPercent = ((1 - state.splitRatio) * 100).toFixed(2);
      pdfPanel.style.flex = `0 0 calc(${{leftPercent}}% - 8px)`;
      issuesPanel.style.flex = `0 0 calc(${{rightPercent}}% - 8px)`;
    }}

    function stopSplitResize() {{
      if (!state.isResizing) return;
      state.isResizing = false;
      workspaceDivider.classList.remove("active");
      document.body.classList.remove("is-resizing");
      window.removeEventListener("mousemove", handleSplitResize);
      window.removeEventListener("mouseup", stopSplitResize);
    }}

    function handleSplitResize(event) {{
      if (!state.isResizing || isStackedLayout() || !workspace) return;
      const bounds = workspace.getBoundingClientRect();
      if (!bounds.width) return;
      state.splitRatio = clamp((event.clientX - bounds.left) / bounds.width, 0.24, 0.76);
      applySplitRatio();
    }}

    function boxKey(match) {{
      if (!match || !Array.isArray(match.bbox)) return "";
      return `${{match.page || 0}}:${{match.bbox.slice(0, 4).join(",")}}`;
    }}

    function sortMatchesByScore(matches) {{
      return asArray(matches)
        .filter((match) => match && Array.isArray(match.bbox))
        .slice()
        .sort((left, right) => Number(right?.score || 0) - Number(left?.score || 0));
    }}

    function severityKey(issue) {{
      const key = safeLower(issue?.severity_key);
      if (key) return key;
      const raw = safeLower(issue?.severity);
      if (raw.includes("high")) return "high";
      if (raw.includes("low")) return "low";
      return "medium";
    }}

    function severityLabel(issue) {{
      const key = severityKey(issue);
      if (REPORT.language === "zh") return key === "high" ? "高" : key === "low" ? "低" : "中";
      return key.charAt(0).toUpperCase() + key.slice(1);
    }}

    function decisionKey(issue) {{
      return safeLower(issue?.recheck_validation?.decision) || safeLower(issue?.vision_validation?.decision) || "unchecked";
    }}

    function decisionLabel(issue) {{
      const key = decisionKey(issue);
      if (key === "keep") return ui.decision_keep;
      if (key === "review") return ui.decision_review;
      if (key === "drop") return ui.decision_drop;
      return ui.decision_unchecked;
    }}

    function bboxLabel(issue) {{
      return preferredTargetMatch(issue) ? ui.bbox_ready : ui.bbox_missing;
    }}

    function matchLabel(kind, match, index) {{
      const baseLabel = kind === "location" ? ui.location : ui.evidence;
      const anchorId = String(match?.anchor_id || "").trim();
      if (anchorId) return `${{baseLabel}} ${{anchorId}}`;
      return index === 0 ? baseLabel : `${{baseLabel}} ${{index + 1}}`;
    }}

    function issueTypes() {{
      const unique = new Set();
      state.issues.forEach((issue) => {{
        const type = issue.type || issue.type_key;
        if (type) unique.add(type);
      }});
      return Array.from(unique);
    }}

    function filteredIssues() {{
      return state.issues.filter((issue) => {{
        const type = issue.type || issue.type_key;
        if (state.selectedType !== "all" && type !== state.selectedType) return false;
        return true;
      }});
    }}

    function currentIssue() {{
      return filteredIssues().find((issue) => issue.client_id === state.selectedIssueId)
        || state.issues.find((issue) => issue.client_id === state.selectedIssueId)
        || null;
    }}

    function fieldText(value, separator = "\\n") {{
      if (Array.isArray(value)) {{
        return value.map((item) => String(item || "").trim()).filter(Boolean).join(separator);
      }}
      return String(value || "").trim();
    }}

    function issueLocationText(issue) {{
      const originalText = fieldText(issue?.location_original);
      if (originalText) return originalText;
      const displayText = fieldText(issue?.location_display);
      if (displayText) return displayText;
      return fieldText(issue?.location);
    }}

    function issueEvidenceText(issue) {{
      const originalText = fieldText(issue?.evidence_original);
      if (originalText) return originalText;
      const displayText = fieldText(issue?.evidence_display);
      if (displayText) return displayText;
      return fieldText(issue?.evidence);
    }}

    function issueReasoningText(issue) {{
      return fieldText(issue?.reasoning, "\\n");
    }}

    function issueFocusTargets(issue, kind = "") {{
      if (!issue) return [];
      const targets = [];
      const seen = new Set();
      const kindFilter = kind === "evidence" ? "evidence" : kind === "location" ? "location" : "";

      const pushTarget = (match, targetKind, index, suffix) => {{
        if (!match || !Array.isArray(match.bbox)) return;
        if (kindFilter && targetKind !== kindFilter) return;
        const signature = boxKey(match);
        if (!signature) return;
        const dedupeKey = `${{targetKind}}:${{signature}}:${{String(match?.anchor_id || "").trim()}}`;
        const targetId = `${{targetKind}}:${{suffix}}:${{signature}}:${{String(match?.anchor_id || "").trim()}}`;
        if (seen.has(dedupeKey)) return;
        seen.add(dedupeKey);
        targets.push({{
          id: targetId,
          kind: targetKind,
          index,
          label: matchLabel(targetKind, match, index),
          match,
        }});
      }};

      const locationMatches = sortMatchesByScore(issue?.location_bbox_matches);
      if (locationMatches.length) {{
        locationMatches.forEach((match, index) => pushTarget(match, "location", index, `loc-${{index}}`));
      }} else if (issue?.best_bbox_match && safeLower(issue?.best_bbox_match_kind) !== "evidence") {{
        pushTarget(issue.best_bbox_match, "location", 0, "best");
      }}

      sortMatchesByScore(issue?.evidence_bbox_matches).forEach((match, index) =>
        pushTarget(match, "evidence", index, `evi-${{index}}`)
      );

      if (!targets.length && issue?.best_bbox_match) {{
        pushTarget(issue.best_bbox_match, "location", 0, "fallback");
      }}

      return targets;
    }}

    function preferredPdfFocusKind(issue, requestedKind = state.pdfFocusKind) {{
      const wantedKind = requestedKind === "evidence" ? "evidence" : "location";
      const hasLocation = issueFocusTargets(issue, "location").length > 0;
      const hasEvidence = issueFocusTargets(issue, "evidence").length > 0;
      if (wantedKind === "location" && hasLocation) return "location";
      if (wantedKind === "evidence" && hasEvidence) return "evidence";
      if (hasLocation) return "location";
      if (hasEvidence) return "evidence";
      return wantedKind;
    }}

    function focusIndexForIssue(issue, kind = state.pdfFocusKind, index = state.pdfFocusIndex) {{
      const targets = issueFocusTargets(issue, kind);
      if (!targets.length) return 0;
      return clamp(index, 0, targets.length - 1);
    }}

    function syncPdfFocusState(issue, reset = false) {{
      const nextKind = preferredPdfFocusKind(issue, reset ? "location" : state.pdfFocusKind);
      const nextIndex = reset ? 0 : focusIndexForIssue(issue, nextKind, state.pdfFocusIndex);
      state.pdfFocusKind = nextKind;
      state.pdfFocusIndex = nextIndex;
      return {{
        kind: nextKind,
        index: nextIndex,
        targets: issueFocusTargets(issue, nextKind),
      }};
    }}

    function currentFocusTarget(issue) {{
      const kind = preferredPdfFocusKind(issue, state.pdfFocusKind);
      const targets = issueFocusTargets(issue, kind);
      return targets[focusIndexForIssue(issue, kind, state.pdfFocusIndex)] || null;
    }}

    function focusTargetCount(kind, issue = currentIssue()) {{
      return issueFocusTargets(issue, kind).length;
    }}

    function focusTargetPositionByKind(kind, issue = currentIssue()) {{
      const normalizedKind = kind === "evidence" ? "evidence" : "location";
      const targets = issueFocusTargets(issue, normalizedKind);
      if (!targets.length) return "";
      const index = state.pdfFocusKind === normalizedKind ? focusIndexForIssue(issue, normalizedKind, state.pdfFocusIndex) : 0;
      return `${{index + 1}} / ${{targets.length}}`;
    }}

    function stepPdfFocus(kind, delta) {{
      const issue = currentIssue();
      if (!issue) return;
      const normalizedKind = kind === "evidence" ? "evidence" : "location";
      const targets = issueFocusTargets(issue, normalizedKind);
      if (!targets.length) return;
      if (state.pdfFocusKind !== normalizedKind) {{
        state.pdfFocusKind = normalizedKind;
        state.pdfFocusIndex = delta < 0 ? targets.length - 1 : 0;
      }} else {{
        const currentIndex = focusIndexForIssue(issue, normalizedKind, state.pdfFocusIndex);
        state.pdfFocusIndex = (currentIndex + delta + targets.length) % targets.length;
      }}
      updateFocusToolbar();
      updateOverlays();
      focusCurrentIssue();
    }}

    function ensureSelection() {{
      const visible = filteredIssues();
      if (!visible.length) {{
        state.selectedIssueId = "";
        return;
      }}
      if (!visible.some((issue) => issue.client_id === state.selectedIssueId)) {{
        state.selectedIssueId = visible[0].client_id;
      }}
    }}

    function preferredLocationMatch(issue) {{
      return sortMatchesByScore(issue?.location_bbox_matches)[0] || issue?.best_bbox_match || sortMatchesByScore(issue?.evidence_bbox_matches)[0] || null;
    }}

    function preferredTargetMatch(issue) {{
      return preferredLocationMatch(issue);
    }}

    function visibleBoxes(issue, pageNumber) {{
      if (!issue) return [];
      const boxes = [];
      const seen = new Set();
      const labelFor = (kind, match, index) => {{
        const baseLabel = kind === "location" ? ui.location : ui.evidence;
        const anchorId = String(match?.anchor_id || "").trim();
        if (anchorId) return `${{baseLabel}} ${{anchorId}}`;
        return index === 0 ? baseLabel : `${{baseLabel}} ${{index + 1}}`;
      }};
      const push = (match, kind, label) => {{
        if (!match || match.page !== pageNumber || !Array.isArray(match.bbox)) return;
        const key = boxKey(match);
        if (!key || seen.has(key)) return;
        seen.add(key);
        boxes.push({{ key, kind, label, bbox: match.bbox.slice(0, 4) }});
      }};

      const locationMatches = sortMatchesByScore(issue.location_bbox_matches);
      const evidenceMatches = sortMatchesByScore(issue.evidence_bbox_matches);
      if (locationMatches.length) {{
        locationMatches.forEach((match, index) => push(match, "location", labelFor("location", match, index)));
      }} else if (!evidenceMatches.length) {{
        push(issue.best_bbox_match, "location", labelFor("location", issue.best_bbox_match, 0));
      }}
      evidenceMatches.forEach((match, index) => push(match, "evidence", labelFor("evidence", match, index)));
      return boxes;
    }}

    function renderTypeChips() {{
      const types = issueTypes();
      const currentType = currentIssue()?.type || currentIssue()?.type_key || "";
      const buttons = [
        `<button class="chip-btn ${{state.selectedType === "all" ? "active" : ""}}" data-type="all">${{ui.all_issues}}</button>`,
        ...types.map((type) => {{
          const stateClass = state.selectedType === type
            ? "active"
            : currentType === type
              ? "current"
              : "";
          return `<button class="chip-btn ${{stateClass}}" data-type="${{type}}">${{type}}</button>`;
        }}),
      ];
      typeChips.innerHTML = buttons.join("");
      typeChips.querySelectorAll("[data-type]").forEach((button) => {{
        button.addEventListener("click", () => {{
          state.selectedType = button.dataset.type || "all";
          ensureSelection();
          syncPdfFocusState(currentIssue(), true);
          renderTypeChips();
          renderIssueList();
          updateFocusToolbar();
          updateOverlays();
        }});
      }});
    }}

    function renderIssueList() {{
      const visible = filteredIssues();
      if (!visible.length) {{
        issueList.innerHTML = `<div class="state-card">${{ui.no_issues}}</div>`;
        return;
      }}
      issueList.innerHTML = visible.map((issue) => {{
        const type = issue.type || issue.type_key || "Issue";
        const bboxPage = preferredTargetMatch(issue)?.page || "";
        const active = currentIssue()?.client_id === issue.client_id ? " active" : "";
        return `
          <button type="button" class="issue-card${{active}}" data-issue-id="${{issue.client_id}}">
            <div class="issue-card-top">
              <div class="issue-badges">
                <span class="type-pill">${{type}}</span>
                <span class="severity-pill severity-pill--${{severityKey(issue)}}">${{severityLabel(issue)}}</span>
                <span class="decision-pill decision-pill--${{decisionKey(issue)}}">${{decisionLabel(issue)}}</span>
              </div>
              <small>${{ui.chunk}} ${{issue.chunk_id ?? "-"}}</small>
            </div>
            <div class="issue-block">
              <span>${{ui.description || (REPORT.language === "zh" ? "\u95ee\u9898\u63cf\u8ff0" : "Description")}}</span>
              <p>${{issue.description || ui.empty_value}}</p>
            </div>
            <div class="issue-block">
              <span>${{ui.reasoning || (REPORT.language === "zh" ? "\u63a8\u7406\u8bf4\u660e" : "Reasoning")}}</span>
              <p>${{issueReasoningText(issue) || ui.empty_value}}</p>
            </div>
            <div class="issue-block">
              <span>${{ui.location}}</span>
              <p>${{issueLocationText(issue) || ui.empty_value}}</p>
            </div>
            <div class="issue-card-foot">
              <span>${{bboxLabel(issue)}}</span>
              <span>${{bboxPage ? `${{ui.page}} ${{bboxPage}}` : ""}}</span>
            </div>
          </button>
        `;
      }}).join("");
      issueList.querySelectorAll("[data-issue-id]").forEach((button) => {{
        button.addEventListener("click", () => {{
          state.selectedIssueId = button.dataset.issueId || "";
          syncPdfFocusState(currentIssue(), true);
          renderTypeChips();
          renderIssueList();
          updateFocusToolbar();
          updateOverlays();
          focusCurrentIssue();
        }});
      }});
    }}

    function renderPages() {{
      pdfStack.innerHTML = "";
      state.pageSections.clear();
      state.pageShells.clear();
      state.pageSizes.clear();
      state.pages.forEach((page) => {{
        const section = document.createElement("section");
        section.className = "pdf-page";

        const label = document.createElement("div");
        label.className = "pdf-page-label";
        label.textContent = `${{ui.page}} ${{page.page_number}}`;

        const shell = document.createElement("div");
        shell.className = "pdf-page-shell";
        shell.dataset.pageNumber = String(page.page_number);
        shell.style.width = `${{page.width * state.zoom}}px`;
        shell.style.height = `${{page.height * state.zoom}}px`;

        const image = document.createElement("img");
        image.className = "pdf-page-image";
        image.src = page.image_data_url;
        image.alt = `${{ui.page}} ${{page.page_number}}`;

        const overlayLayer = document.createElement("div");
        overlayLayer.dataset.overlayLayer = "true";

        shell.appendChild(image);
        shell.appendChild(overlayLayer);
        section.appendChild(label);
        section.appendChild(shell);
        pdfStack.appendChild(section);

        state.pageSections.set(page.page_number, section);
        state.pageShells.set(page.page_number, shell);
        state.pageSizes.set(page.page_number, {{
          width: page.width * state.zoom,
          height: page.height * state.zoom,
        }});
      }});
      updateOverlays();
    }}

    function updateOverlays() {{
      const issue = currentIssue();
      const activeTargetId = currentFocusTarget(issue)?.id || "";
      const normalizedSize = Number(REPORT?.bbox_debug_summary?.bbox_normalized_size || 1000);
      state.pageShells.forEach((shell, pageNumber) => {{
        const overlayLayer = shell.querySelector("[data-overlay-layer]");
        if (!overlayLayer) return;
        overlayLayer.innerHTML = "";
        const pageSize = state.pageSizes.get(pageNumber);
        if (!issue || !pageSize) return;
        issueFocusTargets(issue)
          .filter((target) => target.match.page === pageNumber)
          .forEach((target) => {{
          const box = {{
            kind: target.kind,
            label: target.label,
            bbox: target.match.bbox,
            active: target.id === activeTargetId,
          }};
          const [x1, y1, x2, y2] = box.bbox;
          const element = document.createElement("div");
          element.className = `pdf-overlay pdf-overlay--${{box.kind}}${{box.active ? " pdf-overlay--active" : ""}}`;
          element.style.left = `${{(x1 / normalizedSize) * pageSize.width}}px`;
          element.style.top = `${{(y1 / normalizedSize) * pageSize.height}}px`;
          element.style.width = `${{((x2 - x1) / normalizedSize) * pageSize.width}}px`;
          element.style.height = `${{((y2 - y1) / normalizedSize) * pageSize.height}}px`;
          const tag = document.createElement("span");
          tag.textContent = box.label;
          element.appendChild(tag);
          overlayLayer.appendChild(element);
        }});
      }});
    }}

    function updateFocusToolbar() {{
      const issue = currentIssue();
      const totalPages = REPORT.page_count || 0;
      const zoomText = `${{Math.round(state.zoom * 100)}}%`;
      pageInput.value = String(state.currentPage);
      pageCount.textContent = `/ ${{totalPages}}`;
      zoomValue.textContent = zoomText;
      pageCompactValue.textContent = `${{state.currentPage}} / ${{totalPages}}`;
      zoomCompactValue.textContent = zoomText;

      const atFirstPage = !totalPages || state.currentPage <= 1;
      const atLastPage = !totalPages || state.currentPage >= totalPages;
      prevPage.disabled = atFirstPage;
      prevPageCompact.disabled = atFirstPage;
      nextPage.disabled = atLastPage;
      nextPageCompact.disabled = atLastPage;

      locationCounter.textContent = focusTargetPositionByKind("location", issue) || "-";
      evidenceCounter.textContent = focusTargetPositionByKind("evidence", issue) || "-";
      const hasLocation = focusTargetCount("location", issue) > 0;
      const hasEvidence = focusTargetCount("evidence", issue) > 0;
      locationPrev.disabled = !hasLocation;
      locationNext.disabled = !hasLocation;
      evidencePrev.disabled = !hasEvidence;
      evidenceNext.disabled = !hasEvidence;
      locationFocusGroup.classList.toggle("active", hasLocation && preferredPdfFocusKind(issue, state.pdfFocusKind) === "location");
      evidenceFocusGroup.classList.toggle("active", hasEvidence && preferredPdfFocusKind(issue, state.pdfFocusKind) === "evidence");
    }}

    function focusCurrentIssue(behavior = "smooth") {{
      const issue = currentIssue();
      const match = currentFocusTarget(issue)?.match || preferredTargetMatch(issue);
      if (!match) return;
      const shell = state.pageShells.get(match.page);
      const pageSize = state.pageSizes.get(match.page);
      if (!shell || !pageSize) return;
      const normalizedSize = Number(REPORT?.bbox_debug_summary?.bbox_normalized_size || 1000);
      const [x1, y1, x2, y2] = match.bbox || [0, 0, 0, 0];
      const containerRect = pdfScroll.getBoundingClientRect();
      const shellRect = shell.getBoundingClientRect();
      const bboxCenterX = ((x1 + x2) / 2 / normalizedSize) * pageSize.width;
      const bboxCenterY = ((y1 + y2) / 2 / normalizedSize) * pageSize.height;
      const top = Math.max(0, pdfScroll.scrollTop + (shellRect.top - containerRect.top) + bboxCenterY - (pdfScroll.clientHeight * 0.42));
      const left = Math.max(0, pdfScroll.scrollLeft + (shellRect.left - containerRect.left) + bboxCenterX - (pdfScroll.clientWidth * 0.45));
      pdfScroll.scrollTo({{ left, top, behavior }});
      state.currentPage = match.page;
      updateFocusToolbar();
    }}

    function syncPageFromScroll() {{
      const containerTop = pdfScroll.getBoundingClientRect().top;
      let closestPage = state.currentPage;
      let closestDistance = Number.POSITIVE_INFINITY;
      state.pageShells.forEach((shell, pageNumber) => {{
        const distance = Math.abs(shell.getBoundingClientRect().top - containerTop - 12);
        if (distance < closestDistance) {{
          closestDistance = distance;
          closestPage = pageNumber;
        }}
      }});
      state.currentPage = closestPage;
      updateFocusToolbar();
    }}

    pdfScroll.addEventListener("scroll", syncPageFromScroll);
    prevPage.addEventListener("click", () => {{
      const target = Math.max(1, state.currentPage - 1);
      state.currentPage = target;
      updateFocusToolbar();
      const pageShell = state.pageShells.get(target);
      if (pageShell) pageShell.scrollIntoView({{ behavior: "smooth", block: "start" }});
    }});
    nextPage.addEventListener("click", () => {{
      const target = Math.min(REPORT.page_count || 1, state.currentPage + 1);
      state.currentPage = target;
      updateFocusToolbar();
      const pageShell = state.pageShells.get(target);
      if (pageShell) pageShell.scrollIntoView({{ behavior: "smooth", block: "start" }});
    }});
    pageInput.addEventListener("change", () => {{
      const target = Math.min(Math.max(Number(pageInput.value || 1), 1), REPORT.page_count || 1);
      state.currentPage = target;
      updateFocusToolbar();
      const pageShell = state.pageShells.get(target);
      if (pageShell) pageShell.scrollIntoView({{ behavior: "smooth", block: "start" }});
    }});
    zoomIn.addEventListener("click", () => {{
      state.zoom = Math.min(Number((state.zoom + 0.1).toFixed(2)), 2.4);
      updateFocusToolbar();
      renderPages();
      focusCurrentIssue("auto");
    }});
    zoomOut.addEventListener("click", () => {{
      state.zoom = Math.max(Number((state.zoom - 0.1).toFixed(2)), 0.7);
      updateFocusToolbar();
      renderPages();
      focusCurrentIssue("auto");
    }});
    prevPageCompact.addEventListener("click", () => prevPage.click());
    nextPageCompact.addEventListener("click", () => nextPage.click());
    zoomInCompact.addEventListener("click", () => zoomIn.click());
    zoomOutCompact.addEventListener("click", () => zoomOut.click());
    locationPrev.addEventListener("click", () => stepPdfFocus("location", -1));
    locationNext.addEventListener("click", () => stepPdfFocus("location", 1));
    evidencePrev.addEventListener("click", () => stepPdfFocus("evidence", -1));
    evidenceNext.addEventListener("click", () => stepPdfFocus("evidence", 1));
    workspaceDivider.addEventListener("mousedown", (event) => {{
      if (isStackedLayout()) return;
      event.preventDefault();
      state.isResizing = true;
      workspaceDivider.classList.add("active");
      document.body.classList.add("is-resizing");
      window.addEventListener("mousemove", handleSplitResize);
      window.addEventListener("mouseup", stopSplitResize);
    }});
    window.addEventListener("resize", applySplitRatio);

    applySplitRatio();
    renderTypeChips();
    ensureSelection();
    syncPdfFocusState(currentIssue(), true);
    renderIssueList();
    renderPages();
    updateFocusToolbar();
    focusCurrentIssue("auto");
  </script>
</body>
</html>
"""
