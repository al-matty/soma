"""Tests for the extract module — file-suffix routing and text-input path."""

import json
from pathlib import Path
from types import SimpleNamespace

import pytest

from extract import SUPPORTED_SUFFIXES, extract_api, extract_fenced_block


def _stub_anthropic_response(payload: dict) -> SimpleNamespace:
    """Build a fake anthropic Messages.create response with one text block."""
    block = SimpleNamespace(text=json.dumps(payload))
    return SimpleNamespace(content=[block])


@pytest.fixture
def stub_client(monkeypatch):
    """Replace anthropic.Anthropic with a recording stub.

    Returns a dict that will be filled with {'kwargs': <last create() kwargs>}.
    """
    monkeypatch.setattr("config.ANTHROPIC_API_KEY", "sk-test-key")
    monkeypatch.setattr("extract.ANTHROPIC_API_KEY", "sk-test-key")

    captured: dict = {}
    payload = {
        "biomarkers": [],
        "document_summary": "## Test summary\nNarrative content only.",
        "metadata": {
            "report_type": "other",
            "report_date": "2026-05-26",
            "provider": "Patient Self-Note",
            "tags": ["patient_note"],
            "baseline_candidates": [],
        },
    }

    class _Messages:
        def create(self, **kwargs):
            captured["kwargs"] = kwargs
            return _stub_anthropic_response(payload)

    class _Client:
        def __init__(self, *args, **kwargs):
            self.messages = _Messages()

    import anthropic

    monkeypatch.setattr(anthropic, "Anthropic", _Client)
    return captured


def test_fenced_block_strips_language_tag():
    """A ```json fenced block returns only its inner content."""
    assert extract_fenced_block('```json\n{"a": 1}\n```') == '{"a": 1}'


def test_fenced_block_ignores_leading_prose():
    """Reasoning before the fence is discarded (baseline's YAML case)."""
    text = "Here is my proposal:\n```yaml\nkey: value\n```\nDone."
    assert extract_fenced_block(text) == "key: value"


def test_fenced_block_bare_fence():
    """A fence with no language tag still yields its content."""
    assert extract_fenced_block("```\nplain\n```") == "plain"


def test_fenced_block_no_fence_passthrough():
    """Unfenced text is returned stripped."""
    assert extract_fenced_block('  {"a": 1}  ') == '{"a": 1}'


def test_unsupported_suffix_raises(tmp_path):
    """Files outside SUPPORTED_SUFFIXES are rejected before any API call."""
    bogus = tmp_path / "report.docx"
    bogus.write_text("ignored")
    with pytest.raises(ValueError, match="Unsupported file type"):
        extract_api(bogus, raw_dir=tmp_path / "raw", findings_dir=tmp_path / "findings")


def test_supported_suffixes_constant():
    """The supported set is exactly the documented three."""
    assert SUPPORTED_SUFFIXES == {".pdf", ".md", ".txt"}


def test_markdown_routes_through_text_content(tmp_path, stub_client, monkeypatch):
    """A .md file is sent as a text content block, not a document block."""
    monkeypatch.setattr("redact.PROFILE_DIR", tmp_path)  # no redact.yml -> no PII pass

    note = tmp_path / "2026-05-26_utp1_note.md"
    note.write_text("# UTP1 note\nGums healthy, no bleeding.")

    raw_dir = tmp_path / "raw"
    findings_dir = tmp_path / "findings"
    result, paths = extract_api(note, raw_dir=raw_dir, findings_dir=findings_dir)

    sent = stub_client["kwargs"]
    content = sent["messages"][0]["content"]
    # First block carries the document text, second carries the prompt
    assert content[0]["type"] == "text"
    assert "Gums healthy" in content[0]["text"]
    assert "<document>" in content[0]["text"]
    # No PDF document block was attached
    assert not any(b.get("type") == "document" for b in content)

    # Output artifacts exist
    assert Path(paths["json_path"]).exists()
    assert Path(paths["markdown_path"]).exists()
    assert result.source_file == "2026-05-26_utp1_note.md"


def test_text_path_applies_redaction(tmp_path, stub_client, monkeypatch):
    """PII strings from profile/redact.yml are masked before the API call."""
    monkeypatch.setattr("redact.PROFILE_DIR", tmp_path)
    (tmp_path / "redact.yml").write_text("redact:\n  - Max Mustermann\n")

    note = tmp_path / "patient_note.txt"
    note.write_text("Visit by Max Mustermann on 2026-05-26.")

    extract_api(note, raw_dir=tmp_path / "raw", findings_dir=tmp_path / "findings")

    sent_text = stub_client["kwargs"]["messages"][0]["content"][0]["text"]
    assert "Max Mustermann" not in sent_text
    assert "[REDACTED_1]" in sent_text
