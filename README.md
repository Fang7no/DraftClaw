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

- **Paper pre-submissioncheck**  
  Detect issues in structure, argumentation, clarity, and writing before submitting to journals or conferences.

- **Thesis pre-submission review**  
  Run a comprehensive inspection before final delivery, reducing the chance of major concerns raised by advisors or committee members.

- **Grant application self-review**  
  Verify logical completeness, writing quality, and proposal clarity before submission, lowering the risk of early-stage rejection.

- **Formal research document review**  
  Apply the same workflow to technical reports, white papers, project documents, or other materials requiring rigorous review.

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

### ⏱️ Runtime and Token Cost

|  | Document Size | Deep Mode | Standard Mode | Fast Mode |
|---|---|---|---|---|
| **Thesis** | 73 pages / 52k tokens | 45 min / 1.2M tokens | 37 min / 0.97M tokens | 30 min / 0.67M tokens |
| **Paper** | 12 pages / 12k tokens | 12 min / 0.31M tokens | 9 min / 0.23M tokens | 7 min / 0.16M tokens |

All results above were measured under the Advanced option configuration. Actual runtime and token cost may vary depending on the base model you choose.

### 📌 Detection Results

Taking the Thesis of the woman involved in the Wuhan University library incident as an example.

#### 📝 [PDF Annotations](./example/Example_draftclaw_annotated.pdf) *(Download to view)*

<small>Note: For the best annotation experience, open the file with WPS or a dedicated PDF reader. Edge has limited annotation support.</small>

<img src="./example/example_pdf.png" alt="example-png" width="65%" style="border:1px solid #ddd; padding:3px;">

#### 🌐 [HTML Report](./example/Example_draftclaw_report.html) *(Download to view)*

<img src="./example/example_html.png" alt="example-png" width="80%" style="border:1px solid #ddd; padding:3px;">

### 🖥️ System Page

<img src="./example/Detection.png" alt="example-png" width="80%" style="border:1px solid #ddd; padding:3px;">

---

## ⚡ Quick Start

### 1️⃣ Install

Assuming `Python 3.10+` is already available, the commands below cover everything from `git clone` to the point right before **Configure**.

```powershell
git clone https://github.com/Fang7no/DraftClaw.git
cd DraftClaw
python -m venv .venv
.venv\Scripts\activate
python -m pip install --upgrade pip
python -m pip install -e .
```

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

## 🔐 Configuration

After the following configuration, you can use [test_paper](./test_paper.pdf) to perform a quick test.

<img src="./example/config.png" alt="config-png" width="100%" style="border:1px solid #ddd; padding:3px;">

### 1️⃣ Open System Settings

After launching the system, click **System Settings** to enter the configuration page.

### 2️⃣ Core Services (**Required**)

These are the foundational services the system depends on. You must complete this step before anything else.

#### 📄 PDF Parsing

Used for parsing and structuring academic PDF documents.

- Go to [MinerU](https://mineru.net/) and sign up for an **API Key**
- **Completely free**

#### 🌐 Web Search

Used for external knowledge retrieval and fact verification.

- **Default option**: DuckDuckGo  
  Works out of the box and is **completely free**
- **Advanced option**: [Serper](https://serper.dev/)  
  Sign up to get an **API Key** with a **free tier**

### 3️⃣ Review Model (**Required**)

The Review Model is the core model of the system. It is responsible for the main paper review and error detection workflow.

- **Starter**: `qwen3-235b-a22b-instruct-2507`
- **Advanced**: `gpt-5.4-2026-03-05`

### 4️⃣ Recheck Model (**Required in Standard / Deep Modes**)

In **Standard** and **Deep** modes, the system performs a second-pass verification step. That means you must also configure the Recheck Model.

**Recheck LLM**. Used to verify and re-evaluate the initial review results.

- **Starter**: `qwen3.5-plus-2026-02-15`
- **Advanced**: `Gemini 3.1 Pro`

**Recheck VLM**. Used for visual verification of figures, layouts, screenshots, and other visual evidence.

- **Starter**: `qwen3-vl-plus-2025-12-19`
- **Advanced**: `Gemini 3 Flash`

### 💡 Configuration Tips

For the best review quality, we recommend the following setup strategy:

- **Review Model**: choose the **strongest official model** available on your platform
- **Recheck LLM**: choose a model from a **different family** than the Review Model to reduce same-model bias
- **Recheck VLM**: choose the **strongest official vision-language model** available

You are free to choose models based on your own budget, speed, and availability preferences.

### Where to Get API Keys

You can obtain API keys for different model families from the following platforms:

- **Qwen models**: apply at [DashScope](https://dashscope.console.aliyun.com/)    **free quota**
- **GPT models**: apply at [OpenAI](https://platform.openai.com/)    **Paid**
- **Gemini models**: apply at [Google AI Studio](https://aistudio.google.com/)    **Paid**

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
