from __future__ import annotations

from dataclasses import dataclass
from html import escape
import json
from pathlib import Path

from draftclaw._core.contracts import DocumentText, ErrorGroup, ErrorItem, ModeResult
from draftclaw._core.enums import ErrorType


@dataclass(frozen=True)
class ErrorGroupSpec:
    label: str
    order: int
    color: str
    members: tuple[ErrorType, ...]


ERROR_GROUP_SPECS: tuple[ErrorGroupSpec, ...] = (
    ErrorGroupSpec(
        label="Language Expression Errors",
        order=1,
        color="#c96a4a",
        members=(ErrorType.LANGUAGE_EXPRESSION_ISSUE,),
    ),
    ErrorGroupSpec(
        label="Knowledge Background Errors",
        order=2,
        color="#3f7a8c",
        members=(ErrorType.FACTUAL_ERROR,),
    ),
    ErrorGroupSpec(
        label="Numerical and Calculation Errors",
        order=3,
        color="#8d5fa8",
        members=(ErrorType.CALCULATION_NUMERICAL_ERROR,),
    ),
    ErrorGroupSpec(
        label="Methodological Logic Errors",
        order=4,
        color="#4e7b57",
        members=(ErrorType.METHOD_LOGIC_ERROR,),
    ),
    ErrorGroupSpec(
        label="Experimental Operational Defects",
        order=5,
        color="#b58538",
        members=(ErrorType.EXPERIMENT_PROTOCOL_DEFECT, ErrorType.MEASUREMENT_OPERATIONALIZATION_ISSUE),
    ),
    ErrorGroupSpec(
        label="Distorted Claims",
        order=6,
        color="#9d4f70",
        members=(ErrorType.CLAIM_DISTORTION,),
    ),
    ErrorGroupSpec(
        label="Falsified Citations",
        order=7,
        color="#795548",
        members=(ErrorType.CITATION_FABRICATION,),
    ),
    ErrorGroupSpec(
        label="Contextual Misalignment",
        order=8,
        color="#546e7a",
        members=(ErrorType.CONTEXT_MISALIGNMENT,),
    ),
    ErrorGroupSpec(
        label="Inconsistency between Text and Figures",
        order=9,
        color="#287d8e",
        members=(ErrorType.TEXT_FIGURE_MISMATCH,),
    ),
)

_SPEC_BY_ERROR_TYPE = {member: spec for spec in ERROR_GROUP_SPECS for member in spec.members}
_GROUP_DISPLAY_LABELS = {
    "Language Expression Errors": "语言表达错误",
    "Knowledge Background Errors": "知识背景错误",
    "Numerical and Calculation Errors": "数值与计算错误",
    "Methodological Logic Errors": "方法逻辑错误",
    "Experimental Operational Defects": "实验操作缺陷",
    "Distorted Claims": "结论表述失真",
    "Falsified Citations": "伪造或失实引用",
    "Contextual Misalignment": "上下文不一致",
    "Inconsistency between Text and Figures": "图文不一致",
}


def _group_display_label(label: str) -> str:
    return _GROUP_DISPLAY_LABELS.get(label, label)


def _document_title(document: DocumentText) -> str:
    file_name = str(document.metadata.get("file_name", "")).strip()
    if file_name:
        return file_name
    return Path(document.path).name or document.path


def prepare_mode_result(result: ModeResult) -> ModeResult:
    grouped = _build_grouped_errors(result.errorlist)

    ordered_errors: list[ErrorItem] = []
    error_groups: list[ErrorGroup] = []
    next_id = 1
    for spec, items in grouped:
        normalized_items: list[ErrorItem] = []
        for item in items:
            normalized = item.model_copy(update={"id": next_id}, deep=True)
            normalized_items.append(normalized)
            ordered_errors.append(normalized)
            next_id += 1
        error_groups.append(
            ErrorGroup(
                error_type=spec.label,
                sort_order=spec.order,
                color=spec.color,
                error_count=len(normalized_items),
                errorlist=normalized_items,
            )
        )

    return result.model_copy(
        update={
            "errorlist": ordered_errors,
            "error_groups": error_groups,
        },
        deep=True,
    )


def render_markdown_summary(result: ModeResult) -> str:
    lines = [
        f"# DraftClaw 审查结果（{result.mode.value}）",
        "",
        f"- 检查项数量: {len(result.checklist)}",
        f"- 错误数量: {len(result.errorlist)}",
        f"- LLM 调用次数: {result.stats.llm_calls}",
        f"- 模式耗时(ms): {result.stats.latency_ms}",
        f"- 解析后端: {result.stats.parser_backend}",
        "",
        "## 总结",
        result.final_summary or "（空）",
        "",
        "## 错误概览",
    ]
    for group in result.error_groups:
        lines.append(f"- {_group_display_label(group.error_type)}: {group.error_count}")

    lines.append("")
    lines.append("## 错误分组")
    non_empty_groups = [group for group in result.error_groups if group.error_count > 0]
    if not non_empty_groups:
        lines.append("- （空）")
    for group in non_empty_groups:
        lines.append(f"### {_group_display_label(group.error_type)}（{group.error_count}）")
        for item in group.errorlist:
            lines.extend(
                [
                    f"#### {item.id}.",
                    f"- 错误类型键: {item.error_type.value}",
                    f"- 错误位置: {item.error_location}",
                    f"- 错误原因: {item.error_reason}",
                    f"- 推理链: {item.error_reasoning}",
                ]
            )
        lines.append("")

    lines.append("## 检查清单")
    if not result.checklist:
        lines.append("- （空）")
    for idx, item in enumerate(result.checklist, start=1):
        lines.extend(
            [
                f"### {idx}.",
                f"- 位置: {item.check_location}",
                f"- 说明: {item.check_explanation}",
            ]
        )
    return "\n".join(lines)


def render_html_report(result: ModeResult, document: DocumentText) -> str:
    document_title = _document_title(document)
    groups_payload = [
        {
            "error_type": group.error_type,
            "display_label": _group_display_label(group.error_type),
            "sort_order": group.sort_order,
            "color": group.color,
            "error_count": group.error_count,
            "errorlist": [item.model_dump(mode="json") for item in group.errorlist],
        }
        for group in result.error_groups
    ]
    return f"""<!DOCTYPE html>
<html lang="zh-CN">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>{escape(document_title)} - DraftClaw 审查报告</title>
  <style>
    :root {{
      --paper: #f7f1e6;
      --paper-strong: #efe4d0;
      --ink: #1d2a33;
      --muted: #5f6c72;
      --line: #d9ccb4;
      --line-strong: #c6b08f;
      --shadow: 0 18px 40px rgba(44, 34, 20, 0.12);
      --radius: 18px;
    }}
    * {{ box-sizing: border-box; }}
    body {{
      margin: 0;
      min-height: 100vh;
      background:
        radial-gradient(circle at top left, rgba(201, 106, 74, 0.12), transparent 30%),
        radial-gradient(circle at bottom right, rgba(63, 122, 140, 0.12), transparent 28%),
        linear-gradient(180deg, #f6efe4 0%, #efe5d5 100%);
      color: var(--ink);
      font-family: "Trebuchet MS", "Segoe UI", sans-serif;
    }}
    .shell {{
      display: grid;
      grid-template-columns: minmax(0, 1.02fr) minmax(640px, 1.22fr);
      gap: 18px;
      min-height: 100vh;
      padding: 14px;
    }}
    .panel {{
      border: 1px solid rgba(110, 88, 56, 0.14);
      border-radius: var(--radius);
      background: rgba(251, 247, 239, 0.86);
      box-shadow: var(--shadow);
      backdrop-filter: blur(8px);
      overflow: hidden;
    }}
    .panel-header-top {{
      display: flex;
      align-items: flex-start;
      justify-content: space-between;
      gap: 18px;
    }}
    .panel-header {{
      padding: 18px 22px 14px;
      border-bottom: 1px solid var(--line);
      background: linear-gradient(180deg, rgba(255,255,255,0.42), rgba(255,255,255,0));
    }}
    .eyebrow {{
      margin: 0 0 6px;
      font-size: 12px;
      letter-spacing: 0.12em;
      text-transform: uppercase;
      color: var(--muted);
    }}
    h1, h2, h3, p {{
      margin: 0;
    }}
    .doc-meta {{
      margin-top: 10px;
      display: flex;
      flex-wrap: wrap;
      gap: 10px;
    }}
    .chip {{
      padding: 6px 10px;
      border-radius: 999px;
      border: 1px solid var(--line);
      background: rgba(255,255,255,0.55);
      font-size: 12px;
      color: var(--muted);
    }}
    .document-body {{
      display: grid;
      grid-template-rows: auto minmax(0, 1fr);
      height: calc(100vh - 150px);
      background:
        linear-gradient(transparent 23px, rgba(198, 176, 143, 0.18) 24px),
        linear-gradient(90deg, rgba(201, 106, 74, 0.09) 0 56px, transparent 56px);
      background-size: 100% 24px, 100% 100%;
    }}
    .document-toolbar {{
      display: flex;
      align-items: center;
      justify-content: space-between;
      gap: 12px;
      padding: 14px 22px;
      border-bottom: 1px solid rgba(198, 176, 143, 0.35);
      background: rgba(255,255,255,0.28);
    }}
    .document-toolbar strong {{
      font-size: 14px;
      letter-spacing: 0.02em;
    }}
    .document-status {{
      font-size: 12px;
      color: var(--muted);
    }}
    .document-text {{
      padding: 22px;
      overflow: auto;
      display: grid;
      gap: 14px;
      align-content: start;
    }}
    .document-paragraph {{
      position: relative;
      display: grid;
      grid-template-columns: 44px minmax(0, 1fr);
      gap: 14px;
      padding: 16px 18px;
      border: 1px solid rgba(198, 176, 143, 0.28);
      border-radius: 16px;
      background: rgba(255,255,255,0.34);
      box-shadow: inset 0 1px 0 rgba(255,255,255,0.6);
    }}
    .document-paragraph.has-highlight {{
      border-color: rgba(197, 138, 46, 0.62);
      box-shadow:
        0 0 0 2px rgba(255, 211, 92, 0.18),
        inset 0 1px 0 rgba(255,255,255,0.6);
      background: linear-gradient(180deg, rgba(255, 248, 214, 0.75), rgba(255,255,255,0.44));
    }}
    .paragraph-no {{
      display: inline-flex;
      align-items: center;
      justify-content: center;
      width: 44px;
      height: 28px;
      border-radius: 999px;
      background: rgba(201, 106, 74, 0.12);
      border: 1px solid rgba(201, 106, 74, 0.14);
      color: #8a5c45;
      font-size: 12px;
      font-weight: 700;
      letter-spacing: 0.04em;
    }}
    .paragraph-text {{
      line-height: 1.82;
      font-size: 16px;
      font-family: "Palatino Linotype", "Book Antiqua", "Cambria", serif;
      color: #2f261d;
    }}
    .document-text mark {{
      background: rgba(255, 211, 92, 0.58);
      color: inherit;
      padding: 0.08em 0.16em;
      border-radius: 4px;
      box-shadow: 0 0 0 1px rgba(156, 104, 0, 0.12);
    }}
    .review-layout {{
      display: grid;
      grid-template-rows: auto auto minmax(0, 1fr);
      height: 100vh;
    }}
    .summary {{
      padding: 10px 14px 8px;
      border-bottom: 1px solid var(--line);
      background: linear-gradient(135deg, rgba(255,255,255,0.36), rgba(255,255,255,0));
    }}
    .summary h2 {{
      font-size: 18px;
      line-height: 1.25;
    }}
    .type-grid {{
      padding: 8px 10px 10px;
      display: grid;
      grid-template-columns: repeat(auto-fit, minmax(124px, 1fr));
      gap: 6px;
      border-bottom: 1px solid var(--line);
    }}
    .type-card {{
      display: grid;
      align-content: start;
      border: 1px solid color-mix(in srgb, var(--accent) 24%, white);
      border-radius: 14px;
      min-height: 68px;
      padding: 8px 10px;
      background: linear-gradient(165deg, color-mix(in srgb, var(--accent) 18%, white), rgba(255,255,255,0.88));
      color: var(--ink);
      cursor: pointer;
      text-align: left;
      transition: transform 120ms ease, box-shadow 120ms ease, border-color 120ms ease;
      box-shadow: 0 10px 26px rgba(39, 29, 18, 0.08);
    }}
    .type-card:hover {{
      transform: translateY(-1px);
      box-shadow: 0 14px 28px rgba(39, 29, 18, 0.12);
    }}
    .type-card.is-active {{
      border-color: var(--accent);
      box-shadow: 0 0 0 2px color-mix(in srgb, var(--accent) 28%, white), 0 16px 30px rgba(39, 29, 18, 0.12);
    }}
    .type-card h3 {{
      font-size: 12px;
      line-height: 1.28;
      margin-bottom: 4px;
    }}
    .type-card .count {{
      font-size: 20px;
      line-height: 1;
      font-weight: 700;
      letter-spacing: -0.04em;
    }}
    .detail-shell {{
      display: grid;
      grid-template-columns: minmax(330px, 1.02fr) minmax(0, 1.48fr);
      min-height: 0;
    }}
    .detail-column,
    .list-column {{
      min-height: 0;
      display: grid;
      grid-template-rows: auto minmax(0, 1fr);
    }}
    .section-bar {{
      display: flex;
      align-items: center;
      justify-content: space-between;
      gap: 12px;
      padding: 11px 14px;
      border-bottom: 1px solid var(--line);
      background: rgba(255,255,255,0.34);
    }}
    .section-bar strong {{
      font-size: 14px;
      letter-spacing: 0.08em;
      text-transform: uppercase;
    }}
    .section-bar span {{
      font-size: 12px;
      color: var(--muted);
    }}
    .error-list {{
      border-right: 1px solid var(--line);
      background: rgba(255,255,255,0.32);
      overflow: auto;
    }}
    .error-list button {{
      width: 100%;
      padding: 18px 20px;
      border: 0;
      border-bottom: 1px solid rgba(110, 88, 56, 0.12);
      background: transparent;
      text-align: left;
      cursor: pointer;
      color: var(--ink);
    }}
    .error-list button.is-active {{
      background: rgba(255,255,255,0.62);
    }}
    .error-list .error-top {{
      display: flex;
      align-items: center;
      gap: 8px;
      flex-wrap: wrap;
      margin-bottom: 8px;
    }}
    .error-list .error-number {{
      display: inline-flex;
      align-items: center;
      justify-content: center;
      min-width: 38px;
      padding: 3px 10px;
      border-radius: 999px;
      background: color-mix(in srgb, var(--accent) 18%, white);
      border: 1px solid color-mix(in srgb, var(--accent) 28%, white);
      font-size: 12px;
      font-weight: 700;
    }}
    .error-list .error-key {{
      font-size: 11px;
      color: var(--muted);
      letter-spacing: 0.04em;
      text-transform: uppercase;
    }}
    .error-list .location {{
      display: block;
      color: #2e3d44;
      font-size: 14px;
      line-height: 1.6;
      font-weight: 600;
    }}
    .error-list .preview {{
      display: block;
      margin-top: 8px;
      color: var(--muted);
      font-size: 13px;
      line-height: 1.68;
    }}
    .error-detail {{
      padding: 18px 18px 22px;
      overflow: auto;
      background: linear-gradient(180deg, rgba(255,255,255,0.28), transparent 55%);
    }}
    .detail-card {{
      display: grid;
      gap: 18px;
      border-radius: 18px;
      border: 1px solid color-mix(in srgb, var(--accent) 26%, white);
      background: linear-gradient(180deg, rgba(255,255,255,0.68), rgba(255,255,255,0.42));
      padding: 24px;
      box-shadow: 0 12px 28px rgba(39, 29, 18, 0.08);
    }}
    .detail-head {{
      display: flex;
      align-items: flex-start;
      justify-content: space-between;
      gap: 18px;
    }}
    .detail-card h3 {{
      margin-top: 6px;
      font-size: 22px;
      line-height: 1.3;
    }}
    .detail-badges {{
      display: flex;
      flex-wrap: wrap;
      gap: 8px;
    }}
    .detail-badge {{
      display: inline-flex;
      align-items: center;
      padding: 6px 10px;
      border-radius: 999px;
      border: 1px solid color-mix(in srgb, var(--accent) 24%, white);
      background: color-mix(in srgb, var(--accent) 18%, white);
      font-size: 11px;
      letter-spacing: 0.05em;
      text-transform: uppercase;
    }}
    .detail-section {{
      padding: 18px 20px;
      border-radius: 16px;
      border: 1px solid rgba(198, 176, 143, 0.28);
      background: rgba(255,255,255,0.5);
    }}
    .detail-section.emphasis {{
      background: linear-gradient(180deg, rgba(255,248,214,0.78), rgba(255,255,255,0.52));
      border-color: rgba(197, 138, 46, 0.35);
    }}
    .detail-section .label {{
      display: block;
      margin-bottom: 6px;
      font-size: 12px;
      letter-spacing: 0.08em;
      text-transform: uppercase;
      color: var(--muted);
    }}
    .detail-section .value {{
      line-height: 1.72;
      color: #28363d;
      white-space: pre-wrap;
    }}
    .detail-quote {{
      margin: 0;
      padding: 16px 18px;
      border-left: 4px solid color-mix(in srgb, var(--accent) 64%, white);
      border-radius: 0 12px 12px 0;
      background: rgba(255,255,255,0.72);
      line-height: 1.82;
      font-family: "Palatino Linotype", "Book Antiqua", "Cambria", serif;
      color: #31261d;
    }}
    .detail-text-blocks {{
      display: grid;
      gap: 10px;
    }}
    .detail-paragraph {{
      margin: 0;
      line-height: 1.8;
      color: #2d3a41;
    }}
    .detail-steps {{
      margin: 0;
      padding-left: 22px;
      display: grid;
      gap: 10px;
      color: #2d3a41;
      line-height: 1.8;
    }}
    .detail-steps li::marker {{
      font-weight: 700;
      color: color-mix(in srgb, var(--accent) 70%, #6d4c41);
    }}
    .empty-state {{
      padding: 18px;
      color: var(--muted);
      line-height: 1.6;
    }}
    @media (min-width: 1500px) {{
      .shell {{
        grid-template-columns: minmax(0, 0.95fr) minmax(760px, 1.35fr);
      }}
      .detail-shell {{
        grid-template-columns: minmax(360px, 0.95fr) minmax(0, 1.62fr);
      }}
    }}
    @media (max-width: 980px) {{
      .shell {{
        grid-template-columns: 1fr;
      }}
      .document-body, .review-layout {{
        height: auto;
      }}
      .detail-shell {{
        grid-template-columns: 1fr;
      }}
      .error-list {{
        border-right: 0;
        border-bottom: 1px solid var(--line);
      }}
      .document-body,
      .review-layout {{
        height: auto;
      }}
      .document-text,
      .error-list,
      .error-detail {{
        max-height: none;
      }}
    }}
  </style>
</head>
<body>
  <main class="shell">
    <section class="panel">
      <header class="panel-header">
        <div class="panel-header-top">
          <div>
            <p class="eyebrow">文档</p>
            <h1>{escape(document_title)}</h1>
          </div>
        </div>
        <div class="doc-meta">
          <span class="chip">模式: {escape(result.mode.value)}</span>
          <span class="chip">错误数: {len(result.errorlist)}</span>
          <span class="chip">检查项: {len(result.checklist)}</span>
          <span class="chip">字符数: {len(document.text)}</span>
        </div>
      </header>
      <div class="document-body">
        <div class="document-toolbar">
          <strong>原文内容</strong>
          <span id="highlightStatus" class="document-status">浏览原文</span>
        </div>
        <div id="documentText" class="document-text"></div>
      </div>
    </section>
    <aside class="panel review-layout">
      <section class="summary">
        <p class="eyebrow">审查摘要</p>
        <h2>分组错误导航</h2>
      </section>
      <section id="typeGrid" class="type-grid"></section>
      <section class="detail-shell">
        <div class="list-column">
          <div class="section-bar">
            <strong>当前分组错误</strong>
            <span id="groupMeta">请选择错误类型卡片</span>
          </div>
          <div id="errorList" class="error-list"></div>
        </div>
        <div class="detail-column">
          <div class="section-bar">
            <strong>错误详情</strong>
            <span id="detailMeta">请选择具体错误</span>
          </div>
          <div id="errorDetail" class="error-detail"></div>
        </div>
      </section>
    </aside>
  </main>
  <script>
    const documentText = {json.dumps(document.text, ensure_ascii=False)};
    const errorGroups = {json.dumps(groups_payload, ensure_ascii=False)};
    let activeGroupIndex = -1;
    let activeErrorIndex = -1;

    function escapeHtml(value) {{
      return value
        .replace(/&/g, "&amp;")
        .replace(/</g, "&lt;")
        .replace(/>/g, "&gt;")
        .replace(/"/g, "&quot;")
        .replace(/'/g, "&#39;");
    }}

    function escapeRegExp(value) {{
      return value.replace(/[.*+?^${{}}()|[\\]\\\\]/g, "\\\\$&");
    }}

    function splitParagraphs(value) {{
      return value
        .split(/\\n\\s*\\n+/)
        .map((part) => part.trim())
        .filter(Boolean);
    }}

    function formatTextBlocks(value) {{
      const blocks = splitParagraphs(value);
      if (!blocks.length) {{
        return `<p class="detail-paragraph"></p>`;
      }}
      return `<div class="detail-text-blocks">${{blocks
        .map((block) => `<p class="detail-paragraph">${{escapeHtml(block)}}</p>`)
        .join("")}}</div>`;
    }}

    function formatReasoning(value) {{
      const blocks = splitParagraphs(value);
      if (blocks.length > 1) {{
        return `<div class="detail-text-blocks">${{blocks
          .map((block, index) => `
            <section>
              <span class="label">第 ${'{'}index + 1{'}'} 部分</span>
              <p class="detail-paragraph">${'{'}escapeHtml(block){'}'}</p>
            </section>
          `)
          .join("")}}</div>`;
      }}
      const sentenceMatches = value.match(/[^.!?。！？]+[.!?。！？]?/g) || [];
      const sentences = sentenceMatches.map((item) => item.trim()).filter(Boolean);
      if (sentences.length > 1) {{
        return `<ol class="detail-steps">${{sentences
          .map((sentence) => `<li>${{escapeHtml(sentence)}}</li>`)
          .join("")}}</ol>`;
      }}
      return formatTextBlocks(value);
    }}

    function highlightParagraph(paragraph, phrase) {{
      if (!phrase || !paragraph.includes(phrase)) {{
        return escapeHtml(paragraph);
      }}
      const pattern = new RegExp(escapeRegExp(phrase), "g");
      return escapeHtml(paragraph).replace(pattern, (match) => `<mark>${{match}}</mark>`);
    }}

    function renderDocument(phrase = "") {{
      const host = document.getElementById("documentText");
      const status = document.getElementById("highlightStatus");
      const paragraphs = splitParagraphs(documentText);
      let highlightedCount = 0;

      host.innerHTML = paragraphs
        .map((paragraph, index) => {{
          const contains = phrase && paragraph.includes(phrase);
          if (contains) {{
            highlightedCount += 1;
          }}
          return `
            <article class="document-paragraph ${{contains ? "has-highlight" : ""}}">
              <div class="paragraph-no">段${{index + 1}}</div>
              <div class="paragraph-text">${{highlightParagraph(paragraph, phrase)}}</div>
            </article>
          `;
        }})
        .join("");

      if (!paragraphs.length) {{
        host.innerHTML = `<div class="empty-state">原文内容为空。</div>`;
      }}

      if (!phrase) {{
        status.textContent = "浏览原文";
      }} else if (highlightedCount > 0) {{
        status.textContent = `已高亮 ${{highlightedCount}} 个段落`;
      }} else {{
        status.textContent = "左侧原文中未定位到所选片段";
      }}

      const highlight = host.querySelector(".document-paragraph.has-highlight");
      if (highlight) {{
        highlight.scrollIntoView({{ behavior: "smooth", block: "center" }});
      }}
    }}

    function renderTypeCards() {{
      const host = document.getElementById("typeGrid");
      host.innerHTML = errorGroups.map((group, index) => `
        <button class="type-card ${{index === activeGroupIndex ? "is-active" : ""}}" data-group-index="${{index}}" style="--accent:${{group.color}}">
          <h3>${{escapeHtml(group.display_label)}}</h3>
          <div class="count">${{group.error_count}}</div>
        </button>
      `).join("");
      host.querySelectorAll(".type-card").forEach((button) => {{
        button.addEventListener("click", () => selectGroup(Number(button.dataset.groupIndex)));
      }});
    }}

    function selectGroup(groupIndex) {{
      activeGroupIndex = groupIndex;
      const group = errorGroups[groupIndex];
      activeErrorIndex = group && group.errorlist.length ? 0 : -1;
      document.getElementById("groupMeta").textContent = group
        ? `共 ${{group.error_count}} 项 · ${{group.display_label}}`
        : "请选择错误类型卡片";
      renderTypeCards();
      renderErrorList();
      renderErrorDetail();
    }}

    function renderErrorList() {{
      const host = document.getElementById("errorList");
      const group = errorGroups[activeGroupIndex];
      if (!group || !group.errorlist.length) {{
        host.innerHTML = `<div class="empty-state">当前分类暂无错误。</div>`;
        return;
      }}
      host.innerHTML = group.errorlist.map((item, index) => `
        <button class="${{index === activeErrorIndex ? "is-active" : ""}}" data-error-index="${{index}}" style="--accent:${{group.color}}">
          <div class="error-top">
            <span class="error-number">#${{item.id}}</span>
            <span class="error-key">${{escapeHtml(item.error_type)}}</span>
          </div>
          <span class="location">${{escapeHtml(item.error_location)}}</span>
          <span class="preview">${{escapeHtml(item.error_reason)}}</span>
        </button>
      `).join("");
      host.querySelectorAll("button").forEach((button) => {{
        button.addEventListener("click", () => {{
          activeErrorIndex = Number(button.dataset.errorIndex);
          renderErrorList();
          renderErrorDetail();
        }});
      }});
    }}

    function renderErrorDetail() {{
      const host = document.getElementById("errorDetail");
      const detailMeta = document.getElementById("detailMeta");
      const group = errorGroups[activeGroupIndex];
      if (!group) {{
        host.innerHTML = `<div class="empty-state">尚未选择错误分组。</div>`;
        detailMeta.textContent = "请选择具体错误";
        renderDocument("");
        return;
      }}
      if (!group.errorlist.length || activeErrorIndex < 0) {{
        host.innerHTML = `
          <div class="detail-card" style="--accent:${{group.color}}">
            <h3>${{escapeHtml(group.display_label)}}</h3>
            <section class="detail-section">
              <span class="label">状态</span>
              <div class="value">当前分类暂无错误。</div>
            </section>
          </div>
        `;
        detailMeta.textContent = "请选择具体错误";
        renderDocument("");
        return;
      }}
      const item = group.errorlist[activeErrorIndex];
      detailMeta.textContent = `当前查看错误 #${{item.id}}`;
      host.innerHTML = `
        <div class="detail-card" style="--accent:${{group.color}}">
          <div class="detail-head">
            <div>
              <p class="eyebrow">已选错误</p>
              <h3>#${{item.id}} - ${{escapeHtml(group.display_label)}}</h3>
            </div>
            <div class="detail-badges">
              <span class="detail-badge">${{escapeHtml(item.error_type)}}</span>
              <span class="detail-badge">${{escapeHtml(group.display_label)}}</span>
            </div>
          </div>
          <section class="detail-section emphasis">
            <span class="label">错误位置</span>
            <blockquote class="detail-quote">${{escapeHtml(item.error_location)}}</blockquote>
          </section>
          <section class="detail-section">
            <span class="label">错误原因</span>
            <div class="value">${{formatTextBlocks(item.error_reason)}}</div>
          </section>
          <section class="detail-section">
            <span class="label">推理链</span>
            <div class="value">${{formatReasoning(item.error_reasoning)}}</div>
          </section>
        </div>
      `;
      renderDocument(item.error_location);
    }}

    const firstNonEmpty = errorGroups.findIndex((group) => group.error_count > 0);
    selectGroup(firstNonEmpty >= 0 ? firstNonEmpty : 0);
  </script>
</body>
</html>
"""


def _build_grouped_errors(errorlist: list[ErrorItem]) -> list[tuple[ErrorGroupSpec, list[ErrorItem]]]:
    buckets = {spec.label: [] for spec in ERROR_GROUP_SPECS}
    for item in errorlist:
        spec = _SPEC_BY_ERROR_TYPE.get(item.error_type)
        if spec is None:
            continue
        buckets[spec.label].append(item)
    return [(spec, buckets[spec.label]) for spec in ERROR_GROUP_SPECS]
