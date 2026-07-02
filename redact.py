"""Reusable text-based PII redaction for API calls."""

import yaml

from config import PROFILE_DIR


def load_redact_strings() -> list[str]:
    """Load PII strings from profile/redact.yml, sorted longest-first.

    Returns an empty list if the file doesn't exist or has no entries.
    """
    redact_path = PROFILE_DIR / "redact.yml"
    if not redact_path.exists():
        return []

    strings = (yaml.safe_load(redact_path.read_text()) or {}).get("redact") or []
    if not strings:
        return []

    return sorted(strings, key=len, reverse=True)


def redact_pii(
    text: str, strings: list[str] | None = None
) -> tuple[str, dict[str, str]]:
    """Replace PII strings with deterministic placeholders.

    Args:
        text: The text to redact.
        strings: PII strings to replace, sorted longest-first.
            If None, loads from redact.yml.

    Returns:
        Tuple of (redacted_text, mapping) where mapping is
        {placeholder: original} for use with restore_pii().
    """
    if strings is None:
        strings = load_redact_strings()

    if not strings:
        return text, {}

    mapping: dict[str, str] = {}
    for i, original in enumerate(strings, start=1):
        placeholder = f"[REDACTED_{i}]"
        if original in text:
            text = text.replace(original, placeholder)
            mapping[placeholder] = original

    return text, mapping


def restore_pii(text: str, mapping: dict[str, str]) -> str:
    """Replace placeholders back with original PII strings.

    Args:
        text: Text containing placeholders.
        mapping: The {placeholder: original} dict from redact_pii().

    Returns:
        Text with placeholders replaced by original values.
    """
    for placeholder, original in mapping.items():
        text = text.replace(placeholder, original)
    return text
