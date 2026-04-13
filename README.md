# DraftClaw

<p align="center">
  <img src="https://img.shields.io/badge/Python-3.10+-3776AB?logo=python&logoColor=white" alt="Python 3.10+">
  <img src="https://img.shields.io/badge/Flask-Web_UI-000000?logo=flask&logoColor=white" alt="Flask Web UI">
  <img src="https://img.shields.io/badge/PDF-MinerU%20%2B%20PyMuPDF-D93831?logo=adobeacrobatreader&logoColor=white" alt="PDF pipeline">
  <img src="https://img.shields.io/badge/LLM-Qwen-5B6CFF" alt="Qwen">
  <img src="https://img.shields.io/badge/Export-HTML%20%2B%20Annotated%20PDF-0F766E" alt="Export formats">
</p>

DraftClaw is a local pre-review workspace for academic PDFs. It parses a paper, splits it into chunk-level review units, runs multi-agent issue detection, aligns issues back to PDF bbox locations, and exports both an interactive HTML report and an annotated PDF.

This version is centered on a local Web UI and a chunk-level review pipeline:

- `Plan Agent`: identifies the role and purpose of each chunk
- `Explore Agent`: proposes candidate issues
- `Search Agent`: verifies search-sensitive issues with `current_chunk + search_requests`
- `Summary Agent`: merges staged findings into final chunk issues
- `Recheck Agent`: runs text recheck for every issue and selective vision recheck
- `BBox Locator`: maps issue locations back into the PDF
- `Export`: generates report HTML and a viewer-safe annotated PDF

## Highlights

- Chunk-level review pipeline with `fast / standard / deep` modes
- Dedicated `Recheck Agent`
  - text recheck uses a separate model via `QWEN_RECHECK_MODEL`
  - vision recheck only audits `Language Expression` and `Formula Computation`
- Search-aware verification for factual issues
- PDF bbox localization for issue positions
- Annotated PDF export with native PDF comments
  - optimized popup sizing for readers that support PDF annotations
  - best experience in WPS / Acrobat / other full PDF viewers
- Persistent local task history and logs
- Built-in Web UI for upload, review, filtering, and export

## Workflow

1. Upload a PDF in the Web UI.
2. DraftClaw parses the PDF with MinerU and builds chunk records.
3. Each chunk goes through `Plan -> Explore -> Search -> Summary -> Recheck`.
4. The pipeline resolves issue locations back to PDF bbox regions.
5. The UI displays issues, evidence, process logs, and PDF overlays.
6. You can export:
   - interactive HTML report
   - annotated PDF with issue comments

## Quick Start

### 1. Install

```powershell
python -m venv .venv
.venv\Scripts\activate
python -m pip install --upgrade pip
python -m pip install -e .
```

### 2. Configure

```powershell
copy .env.example .env
notepad .env
```

Minimum required values:

```env
MINERU_API_URL=https://mineru.net/api/v4
MINERU_API_KEY=your_mineru_api_key

REVIEW_API_URL=https://dashscope.aliyuncs.com/compatible-mode/v1
REVIEW_API_KEY=your_review_api_key
REVIEW_MODEL=qwen3-235b-a22b-instruct-2507
```

Optional but commonly adjusted values:

```env
RECHECK_LLM_API_URL=https://dashscope.aliyuncs.com/compatible-mode/v1
RECHECK_LLM_API_KEY=your_recheck_llm_api_key
RECHECK_LLM_MODEL=qwen3-235b-a22b-instruct-2507
RECHECK_VLM_API_URL=https://dashscope.aliyuncs.com/compatible-mode/v1
RECHECK_VLM_API_KEY=your_recheck_vlm_api_key
RECHECK_VLM_MODEL=qwen3-vl-plus-2025-12-19
REPORT_LANGUAGE=zh
SEARCH_ENGINE=duckduckgo
SERPER_API_KEY=
REVIEW_PARALLELISM=2
LLM_REQUEST_MIN_INTERVAL_SECONDS=2.0
```

### 3. Run

```powershell
draftclaw
```

By default, the app starts at:

```text
http://127.0.0.1:5000
```

Useful options:

```powershell
draftclaw --host 127.0.0.1 --port 5000 --no-browser
draftclaw --debug
```

## Review Modes

| Mode | Vision | Search | Typical use |
| --- | --- | --- | --- |
| `fast` | off | off | fastest dry-run pass |
| `standard` | on | off | default paper review |
| `deep` | on | on | most thorough verification |

`Vision` and `Search` are selected by review mode. They are not configured through `.env`.

## Exports

### HTML Report

- interactive standalone HTML export
- issue list, filters, bbox overlays, and report metadata

### Annotated PDF

- red bbox markers locked to issue locations
- interactive comments for PDF readers that support annotations
- note popup contains full issue details when supported by the viewer

Each exported issue note includes:

- `Issues Type`
- `Description`
- `Reasoning`

## Project Structure

```text
.
|-- README.md
|-- .env.example
|-- pyproject.toml
|-- tests/
|-- draftclaw/
|   |-- agents/
|   |-- prompts/
|   |-- web/
|   |-- main.py
|   |-- config.py
|   |-- logger.py
|   |-- bbox_locator.py
|   |-- pdf_annotation_exporter.py
|   |-- report_export_renderer.py
|   `-- cli.py
`-- draftclaw.egg-info/
```

Important runtime data is written under `draftclaw/runtime/` and should not be committed.

## Development

Run the focused workflow tests:

```powershell
python -m pytest -q tests\test_prompt_workflow.py
```

Quick syntax / packaging checks:

```powershell
node --check draftclaw\web\static\app.js
python -m compileall draftclaw
```

## GitHub Upload Boundary

If you want to publish this project to GitHub, use this repository root as the upload root:

```text
DraftClaw_V6/DraftClaw_V6
```

This folder already contains the correct repository-level files:

- `README.md`
- `pyproject.toml`
- `.env.example`
- `.gitignore`
- `draftclaw/`
- `tests/`

Do not upload local runtime or private files such as:

- `.env`
- `draftclaw/runtime/`
- `test_pdf/` if those PDFs are private or just local samples
- `__pycache__/`, `.pytest_cache/`, generated HTML or screenshots
