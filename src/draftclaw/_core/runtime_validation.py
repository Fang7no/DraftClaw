from __future__ import annotations

from pathlib import Path

from draftclaw._core.config import AppConfig

_MASKED_SECRET_VALUES = {"", "***", "your_api_key"}


def runtime_settings_error(
    config: AppConfig,
    *,
    effective_pdf_parse_mode: str | None = None,
    requires_pdf_support: bool = True,
    input_path: str | None = None,
) -> str | None:
    api_key = config.llm.api_key.strip()
    if api_key in _MASKED_SECRET_VALUES:
        return (
            "当前配置中的 API 密钥不可用。"
            "请重新填写真实 API 密钥并保存，然后再提交或重新入队任务。"
        )

    base_url = config.llm.base_url.strip()
    if not base_url:
        return "当前配置不可用：API 接口地址不能为空"
    if base_url.rstrip("/").endswith("/chat/completions"):
        return "当前配置不可用：API 接口地址应填写根地址，而不是 /chat/completions 完整端点"
    if not base_url.startswith(("http://", "https://")):
        return "当前配置不可用：API 接口地址必须以 http:// 或 https:// 开头"
    if not config.llm.model.strip():
        return "当前配置不可用：模型名称不能为空"

    needs_pdf_validation = requires_pdf_support
    if input_path is not None:
        needs_pdf_validation = Path(input_path).suffix.lower() == ".pdf"

    parse_mode = str(effective_pdf_parse_mode or config.parser.pdf_parse_mode).strip().lower() or "fast"
    if needs_pdf_validation and parse_mode == "accurate":
        ocr_url = config.parser.paddleocr_api_url.strip()
        if not ocr_url:
            return "当前配置不可用：PDF 精准模式需要填写 PaddleOCR API 地址"
        if not ocr_url.startswith(("http://", "https://")):
            return "当前配置不可用：PaddleOCR API 地址必须以 http:// 或 https:// 开头"
        ocr_key = config.parser.paddleocr_api_key.strip()
        if ocr_key in _MASKED_SECRET_VALUES:
            return "当前配置不可用：PDF 精准模式需要填写 PaddleOCR Token"
        if not config.parser.paddleocr_api_model.strip():
            return "当前配置不可用：PaddleOCR 模型名称不能为空"

    return None
