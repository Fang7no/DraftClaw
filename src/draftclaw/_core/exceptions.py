class DraftClawError(Exception):
    """Base exception for DraftClaw."""


class InputLoadError(DraftClawError):
    """Raised when an input document cannot be loaded."""


class LLMRequestError(DraftClawError):
    """Raised when the model provider request fails."""


class LLMOutputValidationError(DraftClawError):
    """Raised when the model output cannot be parsed or validated."""

