# DraftClaw: Catch the Flaws Before the Reviewers Do.

DraftClaw 是一个面向论文与研究文档的预审工具。在你把稿件交给 reviewer、导师或合作者之前，先把真正容易被指出的问题抓出来。

传统文档工具只能帮你“看见文字”，DraftClaw 更关心“看见问题”。 它会先解析文档，再给出结构化审查结果，帮助你更快定位硬伤、减少来回返工，也让内部预审更有抓手。

## 使用场景
- **论文投稿前自检**：在正式提交至期刊或会议前，提前发现结构、论证与表达中的潜在问题
- **基金项目提交前自检**：在申报材料提交前，检查逻辑完整性与表达严谨性，降低被初筛淘汰的风险
- **毕业论文提交前自检**：在最终定稿前进行全面排查，减少导师或评审指出的关键性问题
- **其他正式研究文档的预审场景**：适用于各类需要对外提交或内部评审的学术与技术文档

## 例子

[Demo](./mode_result.html)

[Demo](./image.png)

## 如何使用

### 方式一：本地部署后使用 CLI

适合本地统一部署、批量跑文档、希望所有默认参数都集中在一个配置文件里的场景。

#### 1. 安装

```bash
git clone <your-repo-url>
cd DraftClaw
python -m venv .venv
.venv\Scripts\activate
pip install -e draftclaw
```

安装完成后会注册 `draftclaw` 命令。

#### 2. 配置

CLI 模式下，默认配置统一写在 [default.yaml](./src/draftclaw/resources/configs/default.yaml) 中，也可以在脚本文件[document_parser.py](./document_parser.py)中配置。

#### 3. 运行

可以通过**脚本**（推荐）或者**命令行**来进行。

##### 3.1 运行-脚本

参考[document_parser.py](./document_parser.py)，完成**1. 安装**和**2. 配置**后，直接一键运行：
```bash
python document_parser.py
```

##### 3.2 运行-命令行

直接使用 `default.yaml` 中的配置：

```bash
draftclaw review
```

临时覆盖个别参数：

```bash
draftclaw --working-dir output review --input ./test_pdf/whu.pdf --mode standard --run-name demo_review
```

辅助命令：

```bash
draftclaw capabilities
draftclaw validate --result output\runs\20260320\run_xxx\final\mode_result.json
```

结果会输出到 `io.working_dir/runs/.../final/` 下，包括：

- `mode_result.json`
- `mode_result.md`
- `mode_result.html`

### 方式二：pip 安装后用脚本调用（暂未上传pip，敬请期待）

适合你直接给用户一个脚本模板，用户只改脚本顶部配置区就能运行。

#### 1. 安装

```bash
pip install draftclaw
```

#### 2. 配置脚本

推荐直接参考仓库根目录的 [document_parser.py](../document_parser.py)。

最小调用方式如下：

```python
from pathlib import Path

from draftclaw import DraftClaw, ModeName, run_document

INPUT_FILE = Path("paper.pdf")
RUN_REVIEW = True
RUN_MODE = ModeName.STANDARD
RUN_NAME = "demo_review"

API_KEY = "your_api_key"
BASE_URL = "https://api.openai.com/v1"
MODEL = "gpt-4o-mini"

outcome = run_document(
    INPUT_FILE,
    review=RUN_REVIEW,
    mode=RUN_MODE,
    run_name=RUN_NAME,
    api_key=API_KEY,
    base_url=BASE_URL,
    model=MODEL,
)

if outcome.review is not None:
    print(DraftClaw.dump_result(outcome.review.result))
```

如果你只想解析文档，不做审查：

```python
from draftclaw import parse_document, parse_document_text

document = parse_document("paper.pdf")
text = parse_document_text("paper.pdf")
```

## 支持的功能

📄 **文档处理能力**
- **多格式输入**：支持 pdf、docx、txt、md、html/htm、pptx、adoc/asciidoc
- **统一解析**：将不同来源文档转换为结构化文本，便于后续分析
- **长度适配**：支持硕博论文等长文档处理
- **安全可靠**：支持本地部署，保障数据隐私

🔍 **审查与输出能力**
- **结构化结果**：输出 errorlist、error_groups、final_summary 等关键结果
- **多种导出格式**：支持 JSON、Markdown、HTML（推荐使用 HTML 查看完整结果）
- **双模式运行**：
  - fast：整篇快速扫描，适合批量筛查
  - standard：分段逐轮检查并合并问题，适合正式预审

⚙️ **使用方式**
- **CLI + Python API**：既支持命令行直接使用，也可集成到自动化流程中

## 开发与测试

```bash
pytest
```
