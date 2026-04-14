# 🦀 DraftClaw: Catch the Flaws Before the Reviewers Do.

<p align="center">
  <img src="https://img.shields.io/badge/Python-3.10+-3776AB?logo=python&logoColor=white" alt="Python 3.10+">
  <img src="https://img.shields.io/badge/Flask-Web_UI-000000?logo=flask&logoColor=white" alt="Flask Web UI">
  <img src="https://img.shields.io/badge/PDF-MinerU%20%2B%20PyMuPDF-D93831?logo=adobeacrobatreader&logoColor=white" alt="PDF pipeline">
  <img src="https://img.shields.io/badge/LLM-Qwen-5B6CFF" alt="Qwen / ChatGPT">
  <img src="https://img.shields.io/badge/Export-HTML%20%2B%20Annotated%20PDF-0F766E" alt="Export formats">
</p>

<p align="center">
  <b>An AI-powered pre-review assistant for academic papers and research documents.</b><br>
  Surface structure, logic, writing, and factual issues <i>before</i> reviewers, advisors, or collaborators point them out.
</p>

---

## 🎯 What Is DraftClaw?

**DraftClaw** is a pre-review tool built for academic writing.  
Before you submit a paper, thesis, grant proposal, or any formal research document, DraftClaw helps you identify the issues most likely to be flagged during review.

Instead of waiting for reviewers to discover weaknesses in your draft, DraftClaw helps you catch them earlier, fix them faster, and submit with more confidence.

---

## 🚀 Use Cases

- **Pre-submission paper check**  
  Detect issues in structure, argumentation, clarity, and writing before submitting to journals or conferences.

- **Thesis pre-submission review**  
  Run a comprehensive inspection before final delivery, reducing the chance of major concerns raised by advisors or committee members.

- **Grant application self-review**  
  Verify logical completeness, writing quality, and proposal clarity before submission, lowering the risk of early-stage rejection.

- **Formal research document review**  
  Apply the same workflow to technical reports, white papers, project documents, or other materials requiring rigorous review.

---

## ✨ Why It Stands Out

- **Review at the chunk level** for finer-grained issue detection
- **Multiple review depths** with `fast / standard / deep` modes
- **Search-aware verification** for fact-sensitive problems
- **Precise PDF bbox localization** to pinpoint where issues occur
- **Annotated PDF export** with native PDF comments
- **Standalone HTML reports** for easy sharing and filtering
- **Persistent local task history and logs**
- **Built-in Web UI** for upload, review, browsing, and export

---

## 🧠 Core Capabilities

- **✍️ Writing Quality**  
  Improve readability and expression by detecting language issues such as awkward phrasing, ambiguity, inconsistency, and other problems that weaken clarity and professionalism.

- **📚 Knowledge & Factual Accuracy**  
  Identify errors related to background knowledge, established concepts, citations, and factual consistency, helping reduce the risk of incorrect statements or unsupported references.

- **🧩 Logic & Reasoning**  
  Surface weaknesses in argumentation, method design, and conclusion validity, including broken reasoning chains, flawed inference, and claims that are not fully supported by evidence.

- **🧪 Research & Experimental Rigor**  
  Detect critical issues in formulas, computations, experimental setup, evaluation design, and cross-section consistency that may affect the reliability of the research.

- **📍 Location-aware reporting**  
  Map detected issues back to exact PDF regions, making revision faster, easier, and more actionable.

---

## 🎬 Example

Taking the Thesis of the woman involved in the Wuhan University library incident as an example.

### 📌 Detection Results

#### 📝 [PDF Annotations](./example/Example_draftclaw_annotated.pdf) *(Download to view)*

<small>Note: For the best annotation experience, open the file with WPS or a dedicated PDF reader. Edge has limited annotation support.</small>

<img src="./example/example_pdf.png" alt="example-png" width="65%" style="border:1px solid #ddd; padding:3px;">

#### 🌐 [HTML Report](./example/Example_draftclaw_report.html) *(Download to view)*

<img src="./example/example_html.png" alt="example-png" width="80%" style="border:1px solid #ddd; padding:3px;">

### 🖥️ System Page

<!--
#### 🏠 Home
<img src="./example/Home.png" alt="home" width="80%" style="border:1px solid #ddd; padding:3px;">

#### ⚙️ Settings
<img src="./example/Setting.png" alt="setting" width="80%" style="border:1px solid #ddd; padding:3px;">

#### 🔎 Detection
-->

<img src="./example/Detection.png" alt="example-png" width="80%" style="border:1px solid #ddd; padding:3px;">

---

## ⚡ Quick Start

### 1️⃣ Install

```powershell
python -m venv .venv
.venv\Scripts\activate
python -m pip install --upgrade pip
python -m pip install -e .
````

### 2️⃣ Configure

```powershell
copy .env.example .env
```

### 3️⃣ Run

```powershell
draftclaw
```

### 🌍 Open in Browser

By default, the app starts at:

```text
http://127.0.0.1:5000
```

---

## 🔐 Minimum Configuration

```env
MINERU_API_URL=https://mineru.net/api/v4
MINERU_API_KEY=your_mineru_api_key

REVIEW_API_URL=https://dashscope.aliyuncs.com/compatible-mode/v1
REVIEW_API_KEY=your_review_api_key
REVIEW_MODEL=qwen3-235b-a22b-instruct-2507
```

## 🛠️ Optional but Commonly Adjusted Configuration

```env
RECHECK_LLM_API_URL=https://dashscope.aliyuncs.com/compatible-mode/v1
RECHECK_LLM_API_KEY=your_recheck_llm_api_key
RECHECK_LLM_MODEL=qwen3-235b-a22b-instruct-2507

RECHECK_VLM_API_URL=https://dashscope.aliyuncs.com/compatible-mode/v1
RECHECK_VLM_API_KEY=your_recheck_vlm_api_key
RECHECK_VLM_MODEL=qwen3.5-plus-2026-02-15

SEARCH_ENGINE=duckduckgo
SERPER_API_KEY=
```

---

## 🧩 Review Modes

| Mode       | Recheck | Web Search | Typical Use                     |
| ---------- | ------- | ---------- | ------------------------------- |
| `fast`     | off     | off        | Fastest dry-run review          |
| `standard` | on      | off        | Default academic draft review   |
| `deep`     | on      | on         | Most thorough verification pass |

> `Recheck` and `Web Search` are automatically selected based on the chosen review mode.

---

## 📤 Export Outputs

### 🌐 HTML Report

* Standalone interactive HTML export
* Issue list with filters
* Bbox overlays for issue locations
* Review metadata for traceability

### 📝 Annotated PDF

* Red bbox markers aligned to issue positions
* Native PDF comments for supported readers
* Full issue details available in annotation popups when supported

### 🧾 Each Exported Issue Includes

* `Issues Type`
* `Description`
* `Reasoning`

---

## 🖼️ Typical Workflow

1. Upload a draft PDF through the Web UI
2. Choose a review mode: `fast`, `standard`, or `deep`
3. Run the review pipeline
4. Inspect detected issues in the interface
5. Export results as **HTML report** or **annotated PDF**
6. Revise the draft before formal submission

---

## 📁 Project Structure

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

---

## 📌 Notes

Important runtime data is written under:

```text
draftclaw/runtime/
```

---

## 💡 Vision

DraftClaw aims to become the last quality gate before submission —
a practical AI reviewer that helps researchers improve clarity, rigor, and confidence before their work reaches real reviewers.