import re
from typing import Any


_NULL_LIKE_TEXT = {"none", "null", "nil"}


def sanitize_optional_text(value: Any) -> Any:
    if value is None:
        return None

    if not isinstance(value, str):
        return value

    cleaned = re.sub(r"\s+", " ", value).strip()
    if not cleaned:
        return None

    if cleaned.lower() in _NULL_LIKE_TEXT:
        return None

    return cleaned


def sanitize_condition_map(values: dict[str, Any]) -> dict[str, Any]:
    sanitized: dict[str, Any] = {}

    for key, value in values.items():
        normalized = sanitize_optional_text(value)
        if normalized is not None:
            sanitized[key] = normalized

    return sanitized
