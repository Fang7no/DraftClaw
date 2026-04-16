<p align="center">
  <img src="./example/logo.png" alt="example-png" width="20%" style="display: block; margin: 0 auto;">
</p>

# DraftClaw：先于审稿人一步，发现稿件问题。

<p align="center">
  <img src="https://img.shields.io/badge/Python-3.10+-3776AB?logo=python&logoColor=white" alt="Python 3.10+">
  <img src="https://img.shields.io/badge/Flask-Web_UI-000000?logo=flask&logoColor=white" alt="Flask Web UI">
  <img src="https://img.shields.io/badge/PDF-MinerU%20%2B%20PyMuPDF-D93831?logo=adobeacrobatreader&logoColor=white" alt="PDF pipeline">
  <img src="https://img.shields.io/badge/LLM-Qwen-5B6CFF" alt="Qwen / ChatGPT">
  <img src="https://img.shields.io/badge/Export-HTML%20%2B%20Annotated%20PDF-0F766E" alt="Export formats">
</p>

<p align="center">
  <b>面向学术论文与研究文档的 AI 预审工具。</b><br>
  在审稿人、导师或合作者指出问题之前，提前发现结构、逻辑、写作与事实层面的缺陷。
</p>

---

**[English Page](./README.md)**

## 🎯 什么是 DraftClaw？

**DraftClaw** 是一款面向学术写作的预审工具。

在你提交论文、学位论文、基金申请书或其他正式研究文档之前，DraftClaw 可以帮助你识别那些最有可能在评审过程中被指出的问题。  
与其等审稿人来发现草稿中的薄弱环节，不如借助 DraftClaw 更早发现问题、更快完成修正，并更有信心地提交。

---

## 🚀 使用场景

- **论文投稿前预审**  
  在投稿至期刊或会议之前，检测结构、论证、表达清晰度与写作质量等方面的问题。

- **学位论文提交前审查**  
  在最终提交前进行一次全面检查，降低导师或答辩委员会提出重大问题的风险。

- **基金申请自查**  
  在正式提交前核验逻辑完整性、写作质量与方案表达清晰度，减少早期被拒的可能性。

- **正式研究文档审阅**  
  同样适用于技术报告、白皮书、项目文档及其他需要严格审查的正式材料。

---

## 🧠 审查维度

- **✍️ 写作质量**  
  通过检测措辞生硬、表意含糊、术语不一致等语言问题，提高文本的可读性、清晰度与专业性。

- **📚 知识与事实准确性**  
  识别背景知识、既有概念、引用内容与事实一致性相关的问题，降低错误表述或证据不足引用带来的风险。

- **🧩 逻辑与推理**  
  发现论证过程、方法设计与结论有效性中的薄弱环节，包括推理链断裂、推断不成立，以及证据支撑不足的结论。

- **🧪 研究与实验严谨性**  
  检测公式、计算、实验设置、评估设计及跨章节一致性中的关键问题，避免影响研究结果的可靠性。

---

## ✨ 亮点特性

- **📍 位置感知报告:** 可将检测到的问题精确映射回 PDF 中的具体区域，使修改更快速、更直接、更具可操作性。

- **📤 详尽报告：** 支持生成交互式 HTML 报告和带批注的 PDF，便于问题追溯与复查。

- **⚡ 灵活高效：** 提供三种审查模式：**Fast**、**Standard** 和 **Deep**，可满足从快速自查到深度润色的不同需求。

- **🔁 断点恢复：** 审查过程支持中断与恢复，无需担心长文档处理过程中的意外中断。

---

## 🎬 示例

### ⏱️ 运行时间与 Token 消耗

|  | 文档规模 | Deep 模式 | Standard 模式 | Fast 模式 |
|---|---|---|---|---|
| **学位论文** | 73 页 / 52k tokens | 45 分钟 / 1.2M tokens | 37 分钟 / 0.97M tokens | 30 分钟 / 0.67M tokens |
| **论文** | 12 页 / 12k tokens | 12 分钟 / 0.31M tokens | 9 分钟 / 0.23M tokens | 7 分钟 / 0.16M tokens |

以上结果均基于 Advanced option 配置测得。实际运行时间和 Token 消耗会因所选基础模型不同而有所变化。

### 📌 检测结果

以“武汉大学图书馆事件”涉事女生的学位论文为例。

#### 📝 [PDF 批注结果](./example/Example_draftclaw_annotated.pdf) *(下载后查看)*

> [!CAUTION]
> 注意：为获得最佳批注查看体验，请使用 WPS 或专业 PDF 阅读器打开文件。Edge 对批注的支持较为有限。

<img src="./example/example_pdf.png" alt="example-png" width="65%" style="border:1px solid #ddd; padding:3px;">

#### 🌐 [HTML 报告](./example/Example_draftclaw_report.html) *(下载后查看)*

<img src="./example/example_html.png" alt="example-png" width="80%" style="border:1px solid #ddd; padding:3px;">

### 🖥️ 系统页面

<img src="./example/Detection.png" alt="example-png" width="80%" style="border:1px solid #ddd; padding:3px;">

---

## ⚡ 快速开始

### 1️⃣ 安装

假设你已经具备 `Python 3.10+` 环境，下面的命令将覆盖从 `git clone` 到进入 **Configure** 前的全部步骤。

```powershell
git clone https://github.com/Fang7no/DraftClaw.git
cd DraftClaw
python -m venv .venv
.venv\Scripts\activate
python -m pip install --upgrade pip
python -m pip install -e .
```

### 2️⃣ 配置

```powershell
copy .env.example .env
```

### 3️⃣ 运行

```powershell
draftclaw
```

### 🌍 浏览器访问

默认启动地址为：

```text
http://127.0.0.1:5000
```

---

## 🔐 配置说明

完成以下配置后，你可以使用 [test_paper](./test_paper.pdf) 做一次快速测试。

<img src="./example/config.png" alt="config-png" width="100%" style="border:1px solid #ddd; padding:3px;">

### 1️⃣ 打开系统设置

启动系统后，点击 **System Settings** 进入配置页面。

### 2️⃣ 核心服务（必填）

这些是系统运行所依赖的基础服务，必须优先配置。

#### 📄 PDF 解析

用于解析并结构化学术 PDF 文档。

- 前往 [MinerU](https://mineru.net/) 注册并获取 **API Key**
- **完全免费**

#### 🌐 网络搜索

用于外部知识检索与事实核验。

- **默认选项**：DuckDuckGo  
  开箱即用，且 **完全免费**
- **高级选项**：[Serper](https://serper.dev/)  
  注册后可获得带 **免费额度** 的 **API Key**

### 3️⃣ Review Model（必填）

Review Model 是系统的核心模型，负责主要的论文审阅与问题检测流程。

- **Starter**：`qwen3-235b-a22b-instruct-2507`
- **Advanced**：`gpt-5.4-2026-03-05`

### 4️⃣ Recheck Model（仅 Standard / Deep 模式必填）

在 **Standard** 和 **Deep** 模式下，系统会执行第二轮复核，因此还需要配置 Recheck Model。

**Recheck LLM**：用于复核并重新评估初次审阅结果。

- **Starter**：`qwen3.5-plus-2026-02-15`
- **Advanced**：`Gemini 3.1 Pro`

**Recheck VLM**：用于图像、版式、截图等视觉证据的复核。

- **Starter**：`qwen3-vl-plus-2025-12-19`
- **Advanced**：`Gemini 3 Flash`

### 💡 配置建议

为了获得更好的审稿质量，建议采用以下策略：

- **Review Model**：优先选择你所在平台提供的 **最强官方模型**
- **Recheck LLM**：尽量选择与 Review Model **不同家族** 的模型，以减少同模型偏差
- **Recheck VLM**：优先选择 **最强官方视觉语言模型**

你也可以根据预算、速度和可用性自行选择。

### API Key 获取渠道

不同模型家族的 API Key 可以从以下平台获取：

- **Qwen 系列模型**：前往 [DashScope](https://dashscope.console.aliyun.com/) 申请，**有免费额度**
- **GPT 系列模型**：前往 [OpenAI](https://platform.openai.com/) 申请，**付费**
- **Gemini 系列模型**：前往 [Google AI Studio](https://aistudio.google.com/) 申请，**付费**

---

## 🧩 审阅模式

| 模式 | Recheck | Web Search | 典型用途 |
| ---------- | ------- | ---------- | ------------------------------- |
| `fast`     | off     | off        | 最快的快速试跑审阅 |
| `standard` | on      | off        | 默认学术稿件审阅 |
| `deep`     | on      | on         | 最全面的核验流程 |

> `Recheck` 和 `Web Search` 会根据所选审阅模式自动启用或关闭。

---

## 📤 导出结果

### 🌐 HTML 报告

* 独立的交互式 HTML 导出文件
* 支持筛选的问题列表
* 问题位置对应的 bbox 覆盖层
* 便于追溯的审阅元数据

### 📝 标注 PDF

* 与问题位置对齐的红色 bbox 标记
* 在支持的阅读器中可显示原生 PDF 批注
* 如果阅读器支持，可在批注弹窗中查看完整问题详情

### 🧾 每条导出问题包含

* `Issues Type`
* `Description`
* `Reasoning`

---

## 🖼️ 典型工作流程

1. 通过 Web UI 上传待检查的 PDF 稿件
2. 选择审阅模式：`fast`、`standard` 或 `deep`
3. 运行整套审阅流程
4. 在界面中查看检测出的问题
5. 将结果导出为 **HTML 报告** 或 **标注 PDF**
6. 在正式提交前完成修订

---

## 📁 项目结构

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

## 📌 说明

重要运行数据会写入：

```text
draftclaw/runtime/
```

---

## 💡 愿景

DraftClaw 的目标，是成为正式提交前的最后一道防线：它不是替代真实审稿人的工具，而是一个实用的 AI 预审助手，帮助研究者在稿件进入正式评审之前，先把表达、严谨性与整体质量提升到更稳妥的状态。
