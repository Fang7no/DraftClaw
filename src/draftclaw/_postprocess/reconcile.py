from __future__ import annotations

from dataclasses import dataclass

from draftclaw._core.contracts import CheckItem, ErrorItem, LLMRoundOutput
from draftclaw._postprocess.dedup import dedup_review_items, normalize_text


@dataclass
class ReconcileStats:
    merged_checks: int = 0
    merged_errors: int = 0
    removed_checks_by_confirmation: int = 0
    dropped_invalid_errors: int = 0


@dataclass
class ReconcileResult:
    checklist: list[CheckItem]
    errorlist: list[ErrorItem]
    stats: ReconcileStats


def _strip_check_prefix(text: str) -> str:
    stripped = text.strip()
    if stripped.lower().startswith("please check"):
        stripped = stripped[len("please check") :].strip(" :,.，。；;")
    return stripped


def _is_check_confirmed(check: CheckItem, errors: list[ErrorItem]) -> bool:
    check_loc = normalize_text(check.check_location)
    check_exp = normalize_text(_strip_check_prefix(check.check_explanation))
    for error in errors:
        if normalize_text(error.error_location) != check_loc:
            continue
        error_exp = normalize_text(error.error_reason)
        if not check_exp:
            return True
        if check_exp in error_exp or error_exp in check_exp:
            return True
    return False


def filter_confirmed_checklist(checklist: list[CheckItem], errors: list[ErrorItem]) -> list[CheckItem]:
    return [item for item in checklist if not _is_check_confirmed(item, errors)]


def reconcile_round(
    checklist: list[CheckItem],
    errorlist: list[ErrorItem],
    output: LLMRoundOutput,
) -> ReconcileResult:
    stats = ReconcileStats()

    cur_checks = list(checklist)
    cur_errors = list(errorlist)
    incoming_checks = list(output.checklist)

    valid_new_errors: list[ErrorItem] = []
    for item in output.errorlist:
        if not item.error_location.strip() or not item.error_reason.strip() or not item.error_reasoning.strip():
            stats.dropped_invalid_errors += 1
            continue
        valid_new_errors.append(item)

    cur_checks.extend(incoming_checks)
    cur_errors.extend(valid_new_errors)
    stats.merged_checks += len(incoming_checks)
    stats.merged_errors += len(valid_new_errors)

    cur_errors = dedup_review_items(cur_errors)

    before = len(cur_checks)
    cur_checks = filter_confirmed_checklist(cur_checks, cur_errors)
    stats.removed_checks_by_confirmation += before - len(cur_checks)
    cur_checks = dedup_review_items(cur_checks)

    return ReconcileResult(checklist=cur_checks, errorlist=cur_errors, stats=stats)
