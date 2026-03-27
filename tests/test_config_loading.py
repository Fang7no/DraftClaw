from __future__ import annotations

from pathlib import Path
from uuid import uuid4

from draftclaw._core.config import build_config
from draftclaw._core.enums import ModeName
from draftclaw._runtime.service import ReviewService


def _artifact_dir(prefix: str) -> Path:
    root = Path(__file__).resolve().parents[1] / ".test_artifacts"
    path = root / f"{prefix}_{uuid4().hex[:8]}"
    path.mkdir(parents=True, exist_ok=True)
    return path


def test_build_config_reads_direct_yaml_fields() -> None:
    config = build_config(
        {
            "run": {
                "input_file": "paper.pdf",
                "mode": "standard",
                "run_name": "demo_review",
            },
            "llm": {
                "api_key": "test-key",
                "base_url": "https://example.com/v1",
                "model": "demo-model",
                "timeout_sec": 45,
            },
            "io": {
                "working_dir": "output",
            },
            "parser": {
                "pdf_parse_mode": "accurate",
                "paddleocr_api_url": "https://ocr.example/api/parse",
                "paddleocr_api_key": "ocr-key",
                "paddleocr_api_model": "PaddleOCR-VL-1.5",
                "paddleocr_poll_interval_sec": 6,
                "paddleocr_api_timeout_sec": 180,
            },
            "standard": {
                "target_chunks": 0,
            },
        }
    )

    assert config.run.input_file == "paper.pdf"
    assert config.run.mode == ModeName.STANDARD
    assert config.run.run_name == "demo_review"
    assert config.llm.api_key == "test-key"
    assert config.llm.base_url == "https://example.com/v1"
    assert config.llm.model == "demo-model"
    assert config.llm.timeout_sec == 45
    assert config.io.working_dir == "output"
    assert config.parser.pdf_parse_mode == "accurate"
    assert config.parser.paddleocr_api_url == "https://ocr.example/api/parse"
    assert config.parser.paddleocr_api_key == "ocr-key"
    assert config.parser.paddleocr_api_model == "PaddleOCR-VL-1.5"
    assert config.parser.paddleocr_poll_interval_sec == 6
    assert config.parser.paddleocr_api_timeout_sec == 180
    assert config.standard.target_chunks == 0


def test_review_service_uses_working_dir_from_config() -> None:
    working_dir = _artifact_dir("config_runtime")
    config = build_config(
        {
            "llm": {
                "api_key": "test-key",
                "base_url": "https://example.com/v1",
                "model": "demo-model",
            },
            "io": {
                "working_dir": str(working_dir),
            },
        }
    )

    service = ReviewService(config)

    assert service.working_dir == working_dir.resolve()
