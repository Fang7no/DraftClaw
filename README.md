# DraftClaw: Catch the flaws before the reviewers do.

DraftClaw 是一个面向论文与研究文档的预审工具。在你把稿件交给 reviewer、导师或合作者之前，先把真正容易被指出的问题先抓出来。

它先解析文档，再输出结构化审查结果，帮助你更快定位硬伤、减少返工，也让组内预审更有抓手。

## 典型使用场景

- 投稿前自检，先扫语言、数字、上下文一致性和论证漏洞
- 返修后复查，确认没有引入新的冲突和遗漏
- 导师、PI、研究助理做组内预审，先聚焦最值得人工讨论的问题
- 统一解析 PDF、Word、Markdown 等研究文档，作为后续流程入口

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

CLI 模式下，默认配置统一写在 [default.yaml](./src/draftclaw/resources/configs/default.yaml) 中。

最常需要修改的是：

- `run.input_file`
- `llm.api_key`
- `llm.base_url`
- `llm.model`

常用但通常不用频繁改的是：

- `run.mode`
- `run.run_name`
- `io.working_dir`
- `standard.target_chunks`

其中：

- `standard.target_chunks: 0` 表示自动分块
- 自动规则是按 `字符数 / 5000` 取最近奇数，最大不超过 `19`
- 如果你填 `1` 到 `20`，系统就按你指定的分块数执行

#### 3. 运行

直接使用 `default.yaml` 中的配置：

```bash
draftclaw review
```

临时覆盖个别参数：

```bash
draftclaw --working-dir output review --input ./test_pdf/whu.pdf --mode standard --run-name demo_review
```

临时覆盖模型参数：

```bash
draftclaw --api-key your_api_key --base-url https://api.openai.com/v1 --model gpt-4o-mini review
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

### 方式二：pip 安装后用脚本调用

适合你直接给用户一个脚本模板，用户只改脚本顶部配置区就能运行。

#### 1. 安装

```bash
pip install draftclaw
```

#### 2. 配置脚本

推荐直接参考仓库根目录的 [document_parser.py](../document_parser.py)。

脚本顶部已经按三类整理好配置：

- 必须修改：`INPUT_FILE`、`API_KEY`
- 常用可调：`RUN_MODE`、`BASE_URL`、`MODEL`、`WORKING_DIR`
- 高级参数：`ENABLE_MERGE_AGENT`、`TEXT_FAST_PATH`、`CACHE_IN_PROCESS`、`CACHE_ON_DISK`、`DOCLING_PAGE_CHUNK_SIZE`、`CHUNK_COUNT`、`LLM_TIMEOUT_SEC`

其中默认值已经按常规使用场景设好，通常除了 `INPUT_FILE`、`API_KEY`、`BASE_URL`、`MODEL` 之外都不用改。

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

- 多格式输入：支持 `pdf`、`docx`、`txt`、`md`、`html` / `htm`、`pptx`、`adoc` / `asciidoc`
- 文档解析：把不同来源文档转成统一结构化文本
- 结构化审查：输出 `errorlist`、`error_groups`、`final_summary`
- 双模式运行：`fast` 适合快速扫一版，`standard` 适合正式预审
- 多种结果输出：JSON、Markdown、HTML
- CLI + Python API：既能命令行跑，也能嵌入你自己的流程

## 项目特色

- 关注预审价值，优先抓真正会被 reviewer 指出来的问题
- 既能个人自检，也适合团队内审
- CLI 与脚本两条使用路径明确，不再混用多套配置入口
- 解析与审查可以拆开使用

## 开发与测试

```bash
pytest
```
