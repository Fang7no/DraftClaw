from __future__ import annotations

from enum import Enum


class StrEnum(str, Enum):
    def __str__(self) -> str:
        return self.value


class InputType(StrEnum):
    PDF = "pdf"
    DOCX = "docx"
    TXT = "txt"
    MD = "md"
    PPTX = "pptx"
    HTML = "html"
    ASCIIDOC = "asciidoc"
    OTHER = "other"

    @classmethod
    def from_suffix(cls, suffix: str) -> "InputType":
        normalized = suffix.lower()
        mapping = {
            ".pdf": cls.PDF,
            ".docx": cls.DOCX,
            ".txt": cls.TXT,
            ".md": cls.MD,
            ".pptx": cls.PPTX,
            ".html": cls.HTML,
            ".htm": cls.HTML,
            ".adoc": cls.ASCIIDOC,
            ".asciidoc": cls.ASCIIDOC,
        }
        return mapping.get(normalized, cls.OTHER)


class ModeName(StrEnum):
    FAST = "fast"
    STANDARD = "standard"


class ErrorType(StrEnum):
    METHOD_LOGIC_ERROR = "Methodological Logic Errors"
    EXPERIMENT_PROTOCOL_DEFECT = "Experimental Operational Defects"
    CLAIM_DISTORTION = "Distorted Claims"
    CITATION_FABRICATION = "Falsified Citations"
    TEXT_FIGURE_MISMATCH = "Inconsistency between Text and Figures"
    CONTEXT_MISALIGNMENT = "Contextual Misalignment"
    LANGUAGE_EXPRESSION_ISSUE = "Language Expression Errors"
    FACTUAL_ERROR = "Knowledge Background Errors"
    CALCULATION_NUMERICAL_ERROR = "Numerical and Calculation Errors"
    MEASUREMENT_OPERATIONALIZATION_ISSUE = "Experimental Operational Defects"
