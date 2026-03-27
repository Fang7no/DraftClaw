from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from pydantic import BaseModel, Field, field_validator, model_validator

from draftclaw._core.enums import ErrorType, InputType, ModeName


class CheckItem(BaseModel):
    check_location: str = Field(..., min_length=1)
    check_explanation: str = Field(..., min_length=1)

    @field_validator("check_explanation", mode="before")
    @classmethod
    def ensure_prefix(cls, value: Any) -> str:
        text = str(value).strip()
        if not text:
            raise ValueError("check_explanation cannot be empty")
        if text.lower().startswith("please check"):
            return text
        return f"please check {text}"


class ErrorItem(BaseModel):
    id: int = Field(default=0, ge=0)
    error_location: str = Field(..., min_length=1)
    error_type: ErrorType
    error_reason: str = Field(..., min_length=1)
    error_reasoning: str = Field(..., min_length=1)

    @model_validator(mode="before")
    @classmethod
    def migrate_legacy_fields(cls, value: Any) -> Any:
        if not isinstance(value, dict):
            return value
        payload = dict(value)
        legacy_explanation = str(payload.get("error_explanation", "")).strip()
        if legacy_explanation:
            payload.setdefault("error_reason", legacy_explanation)
            payload.setdefault("error_reasoning", legacy_explanation)
        return payload


class ChunkInfo(BaseModel):
    chunk_id: int = Field(..., ge=1)
    start_paragraph: int = Field(..., ge=0)
    end_paragraph: int = Field(..., ge=0)
    paragraph_count: int = Field(..., ge=0)
    char_count: int = Field(..., ge=0)
    token_estimate: int = Field(..., ge=0)


class LLMRoundOutput(BaseModel):
    checklist: list[CheckItem] = Field(default_factory=list)
    errorlist: list[ErrorItem] = Field(default_factory=list)
    notes: str | None = None


class ErrorMergeOutput(BaseModel):
    errorlist: list[ErrorItem] = Field(default_factory=list)
    notes: str | None = None


class DeepPlanItem(BaseModel):
    focus_location: str = Field(..., min_length=1)
    suspected_issue: str = Field(..., min_length=1)
    evidence_summary: str = Field(..., min_length=1)


class DeepPlanOutput(BaseModel):
    plan: list[DeepPlanItem] = Field(default_factory=list)
    notes: str | None = None


class ErrorGroup(BaseModel):
    error_type: str = Field(..., min_length=1)
    sort_order: int = Field(..., ge=1)
    color: str = Field(..., min_length=1)
    error_count: int = Field(default=0, ge=0)
    errorlist: list[ErrorItem] = Field(default_factory=list)


class ModeStats(BaseModel):
    rounds: int = Field(default=0, ge=0)
    llm_calls: int = Field(default=0, ge=0)
    latency_ms: int = Field(default=0, ge=0)
    input_chars: int = Field(default=0, ge=0)
    chunk_count: int = Field(default=0, ge=0)
    parser_backend: str = Field(default="")


class ModeResult(BaseModel):
    mode: ModeName
    checklist: list[CheckItem] = Field(default_factory=list)
    errorlist: list[ErrorItem] = Field(default_factory=list)
    error_groups: list[ErrorGroup] = Field(default_factory=list)
    stats: ModeStats = Field(default_factory=ModeStats)
    final_summary: str = Field(default="")
    trace_refs: list[str] = Field(default_factory=list)


class DocumentText(BaseModel):
    path: str
    input_type: InputType
    text: str
    sha256: str
    file_size: int
    parser_backend: str
    metadata: dict[str, Any] = Field(default_factory=dict)


class InputMeta(BaseModel):
    input_path: str
    input_type: InputType
    file_size: int = Field(..., ge=0)
    sha256: str
    parser_backend: str


class RunTiming(BaseModel):
    started_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    finished_at: datetime | None = None
    duration_ms: int = Field(default=0, ge=0)


class RunRecord(BaseModel):
    run_id: str
    mode: ModeName
    input_meta: InputMeta
    config_snapshot: dict[str, Any]
    prompt_version: str
    timing: RunTiming = Field(default_factory=RunTiming)
    llm_calls: int = Field(default=0, ge=0)
    artifacts: dict[str, str] = Field(default_factory=dict)
