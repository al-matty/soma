"""Tests for text-based PII redaction."""

import pytest

from redact import load_redact_strings, redact_pii, restore_pii


def test_basic_redaction():
    """PII strings are replaced with numbered placeholders."""
    text = "Patient: Max Mustermann, DOB: 01.01.1990"
    strings = ["Max Mustermann", "01.01.1990"]
    redacted, mapping = redact_pii(text, strings)

    assert "Max Mustermann" not in redacted
    assert "01.01.1990" not in redacted
    assert "[REDACTED_1]" in redacted
    assert "[REDACTED_2]" in redacted


def test_longest_first_matching():
    """Longer strings should be replaced before shorter substrings."""
    text = "Name: Matthias Albert, signed by Albert"
    # Sorted longest-first as load_redact_strings would return
    strings = sorted(["Albert", "Matthias Albert"], key=len, reverse=True)
    redacted, mapping = redact_pii(text, strings)

    assert "Matthias [REDACTED_" not in redacted
    assert "[REDACTED_1]" in redacted  # "Matthias Albert" (longest)


def test_restore_roundtrip():
    """Redacting then restoring returns the original text."""
    original = "DOB: 20.06.1986, Name: Matthias Albert"
    strings = ["Matthias Albert", "20.06.1986"]
    redacted, mapping = redact_pii(original, strings)
    restored = restore_pii(redacted, mapping)

    assert restored == original


def test_empty_strings_passthrough():
    """Empty redaction list passes text through unchanged."""
    text = "No PII here"
    redacted, mapping = redact_pii(text, [])

    assert redacted == text
    assert mapping == {}


def test_no_match_passthrough():
    """Strings not found in text produce empty mapping."""
    text = "Vitamin D: 22 ng/mL"
    strings = ["Max Mustermann"]
    redacted, mapping = redact_pii(text, strings)

    assert redacted == text
    assert mapping == {}


def test_restore_empty_mapping():
    """Restoring with empty mapping returns text unchanged."""
    text = "No placeholders"
    assert restore_pii(text, {}) == text


def test_multiple_occurrences():
    """Same PII string appearing multiple times gets same placeholder."""
    text = "Name: Max at start, Max at end"
    strings = ["Max"]
    redacted, mapping = redact_pii(text, strings)

    assert redacted.count("[REDACTED_1]") == 2
    restored = restore_pii(redacted, mapping)
    assert restored == text


def test_mapping_only_contains_found_strings():
    """Mapping only includes PII strings actually found in the text."""
    text = "Just a name: Max"
    strings = ["Max", "01.01.1990", "Berlin"]
    redacted, mapping = redact_pii(text, strings)

    assert len(mapping) == 1


def test_load_missing_file(tmp_path, monkeypatch):
    """Returns empty list when redact.yml doesn't exist."""
    monkeypatch.setattr("redact.PROFILE_DIR", tmp_path)
    assert load_redact_strings() == []


def test_load_empty_redact_key(tmp_path, monkeypatch):
    """Returns empty list when redact key is empty."""
    monkeypatch.setattr("redact.PROFILE_DIR", tmp_path)
    (tmp_path / "redact.yml").write_text("redact: []")
    assert load_redact_strings() == []


def test_load_empty_file(tmp_path, monkeypatch):
    """Returns empty list when redact.yml is empty."""
    monkeypatch.setattr("redact.PROFILE_DIR", tmp_path)
    (tmp_path / "redact.yml").write_text("")
    assert load_redact_strings() == []


def test_load_null_redact_key(tmp_path, monkeypatch):
    """Returns empty list when redact key has no value."""
    monkeypatch.setattr("redact.PROFILE_DIR", tmp_path)
    (tmp_path / "redact.yml").write_text("redact:\n")
    assert load_redact_strings() == []


def test_load_sorted_longest_first(tmp_path, monkeypatch):
    """Loaded strings are sorted longest-first."""
    monkeypatch.setattr("redact.PROFILE_DIR", tmp_path)
    (tmp_path / "redact.yml").write_text(
        'redact:\n  - "Short"\n  - "A longer string"\n'
    )
    result = load_redact_strings()

    assert result[0] == "A longer string"
    assert result[1] == "Short"
