from __future__ import annotations

import hashlib

from draftclaw._core.contracts import CheckItem, ErrorItem


def normalize_text(value: str) -> str:
    return " ".join(value.lower().strip().split())


def _hash_basis(parts: list[str]) -> str:
    basis = "|".join(parts)
    return hashlib.sha1(basis.encode("utf-8")).hexdigest()


def review_item_key(item: CheckItem | ErrorItem) -> str:
    if isinstance(item, CheckItem):
        return _hash_basis(
            [
                "check",
                normalize_text(item.check_location),
                normalize_text(item.check_explanation),
            ]
        )
    return _hash_basis(
        [
            "error",
            normalize_text(item.error_location),
            normalize_text(item.error_type.value),
            normalize_text(item.error_reason),
        ]
    )


def dedup_review_items(items: list[CheckItem] | list[ErrorItem]) -> list:
    bucket: dict[str, CheckItem | ErrorItem] = {}
    for item in items:
        key = review_item_key(item)
        existing = bucket.get(key)
        if existing is None:
            bucket[key] = item
            continue

        if isinstance(item, CheckItem) and isinstance(existing, CheckItem):
            if len(item.check_explanation) >= len(existing.check_explanation):
                bucket[key] = item
            continue

        if isinstance(item, ErrorItem) and isinstance(existing, ErrorItem):
            current_score = len(item.error_reason) + len(item.error_reasoning)
            existing_score = len(existing.error_reason) + len(existing.error_reasoning)
            if current_score >= existing_score:
                bucket[key] = item

    return list(bucket.values())


def renumber_error_items(items: list[ErrorItem]) -> list[ErrorItem]:
    return [item.model_copy(update={"id": idx}, deep=True) for idx, item in enumerate(items, start=1)]
