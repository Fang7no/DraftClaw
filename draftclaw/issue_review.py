"""
Helpers for interpreting per-issue review decisions.
"""

from __future__ import annotations

from typing import Any, Dict


VALID_DECISIONS = {"keep", "drop", "review", "skip", "unchecked"}


def _normalize_decision(value: Any) -> str:
    decision = str(value or "").strip().lower()
    return decision if decision in VALID_DECISIONS else ""


def get_issue_review_decision(issue: Dict[str, Any] | None) -> str:
    """Return the effective review decision for an issue."""
    if not isinstance(issue, dict):
        return "skip"

    for field_name in ("recheck_validation", "vision_validation"):
        payload = issue.get(field_name)
        if not isinstance(payload, dict):
            continue
        decision = _normalize_decision(payload.get("decision"))
        if decision:
            return decision

    return "skip"


def issue_is_dropped(issue: Dict[str, Any] | None) -> bool:
    return get_issue_review_decision(issue) == "drop"


def ensure_issue_review_defaults(
    issue: Dict[str, Any],
    *,
    vision_enabled: bool,
    text_enabled: bool,
) -> Dict[str, Any]:
    """Backfill review metadata when a validation stage did not run."""
    if not isinstance(issue, dict):
        return issue

    text_validation = issue.get("text_validation")
    if not isinstance(text_validation, dict) or not _normalize_decision(text_validation.get("decision")):
        reason = "Text recheck was not executed for this issue."
        if not text_enabled:
            reason = "Text recheck is disabled for this run."
        issue["text_validation"] = {
            "validated": False,
            "decision": "skip",
            "confidence": "low",
            "reason": reason,
            "model": "",
        }

    vision_validation = issue.get("vision_validation")
    if not isinstance(vision_validation, dict) or not _normalize_decision(vision_validation.get("decision")):
        reason = "Vision recheck was not executed for this issue."
        if not vision_enabled:
            reason = "Vision recheck is disabled for this run."
        issue["vision_validation"] = {
            "validated": False,
            "decision": "skip",
            "confidence": "low",
            "reason": reason,
            "model": "",
            "screenshot_count": 0,
        }

    recheck_validation = issue.get("recheck_validation")
    if not isinstance(recheck_validation, dict) or not _normalize_decision(recheck_validation.get("decision")):
        issue["recheck_validation"] = {
            "validated": False,
            "decision": get_issue_review_decision(issue),
            "confidence": "low",
            "reason": "No aggregate recheck decision was recorded.",
            "model": "aggregate",
            "agents_run": {
                "text": bool(text_enabled),
                "vision": bool(vision_enabled),
            },
        }

    return issue
