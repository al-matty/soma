"""Extraction logic - API and manual paths for lab report extraction."""

import base64
import json
import re
from datetime import datetime
from pathlib import Path

from schema import ExtractionResult

from config import (
    ANTHROPIC_API_KEY,
    EXTRACTION_MODEL,
    FINDINGS_DIR,
    PROMPTS_DIR,
    RAW_DIR,
)


def _read_prompt() -> str:
    return (PROMPTS_DIR / "extraction_prompt.txt").read_text()


def extract_fenced_block(text: str) -> str:
    """Return the content of the first triple-backtick code fence.

    Ignores an optional language tag on the opening fence and any prose
    before or after the block. If no fence is present, returns the
    stripped text unchanged. Shared by the extraction (JSON) and baseline
    (YAML) response parsers.
    """
    if "```" not in text:
        return text.strip()
    after_open = text.split("```", 1)[1]
    # Drop the optional language tag on the fence's opening line
    if "\n" in after_open:
        after_open = after_open.split("\n", 1)[1]
    return after_open.split("```", 1)[0].strip()


def _redact_pdf(pdf_path: Path) -> tuple[bytes, bool]:
    """Redact PII strings from PDF before sending to API.

    Returns (pdf_bytes, was_redacted). If profile/redact.yml doesn't exist
    or has no entries, returns original bytes with was_redacted=False.
    """
    from redact import load_redact_strings

    strings = load_redact_strings()
    if not strings:
        return pdf_path.read_bytes(), False

    import pymupdf

    doc = pymupdf.open(pdf_path)
    for page in doc:
        for s in strings:
            for area in page.search_for(s):
                page.add_redact_annot(area, fill=(0, 0, 0))
        page.apply_redactions()

    redacted_bytes = doc.tobytes()
    doc.close()
    return redacted_bytes, True


def _write_outputs(
    result: ExtractionResult,
    raw_dir: Path | None = None,
    findings_dir: Path | None = None,
) -> dict[str, str]:
    """Write JSON and markdown outputs. Returns paths written."""
    raw_dir = raw_dir or RAW_DIR
    findings_dir = findings_dir or FINDINGS_DIR

    # Determine filenames from extraction data
    report_date = result.biomarkers[0].report_date if result.biomarkers else "unknown"
    provider = result.biomarkers[0].provider if result.biomarkers else "unknown"
    provider_slug = re.sub(r"[^a-z0-9]+", "_", provider.lower()).strip("_")
    timestamp = datetime.now().strftime("%H%M%S")

    # Write JSON to data/raw/
    raw_dir.mkdir(parents=True, exist_ok=True)
    json_filename = f"{report_date}_{provider_slug}_{timestamp}.json"
    json_path = raw_dir / json_filename
    json_path.write_text(result.model_dump_json(indent=2))

    # Write markdown to docs/findings/YYYY/
    year = str(report_date)[:4] if str(report_date) != "unknown" else "unknown"
    findings_year_dir = findings_dir / year
    findings_year_dir.mkdir(parents=True, exist_ok=True)
    report_type = result.metadata.report_type
    md_filename = f"{report_date}_{report_type}_{provider_slug}.md"
    md_path = findings_year_dir / md_filename
    md_path.write_text(result.document_summary)

    return {"json_path": str(json_path), "markdown_path": str(md_path)}


SUPPORTED_SUFFIXES = {".pdf", ".md", ".txt"}


def extract_api(
    file_path: Path,
    save_redacted: bool = False,
    raw_dir: Path | None = None,
    findings_dir: Path | None = None,
) -> tuple[ExtractionResult, dict[str, str]]:
    """Extract biomarkers from a PDF, markdown, or plain-text report via Claude API."""
    import anthropic

    raw_dir = raw_dir or RAW_DIR

    suffix = file_path.suffix.lower()
    if suffix not in SUPPORTED_SUFFIXES:
        raise ValueError(
            f"Unsupported file type: {suffix}. Expected one of {sorted(SUPPORTED_SUFFIXES)}."
        )

    if not ANTHROPIC_API_KEY:
        raise ValueError(
            "ANTHROPIC_API_KEY not set. Export it or add to .env file."
        )

    client = anthropic.Anthropic(api_key=ANTHROPIC_API_KEY)
    prompt = _read_prompt()

    pii_mapping: dict[str, str] = {}

    if suffix == ".pdf":
        pdf_bytes, was_redacted = _redact_pdf(file_path)
        if save_redacted and was_redacted:
            raw_dir.mkdir(parents=True, exist_ok=True)
            redacted_path = raw_dir / f"{file_path.stem}_redacted.pdf"
            redacted_path.write_bytes(pdf_bytes)
        pdf_b64 = base64.b64encode(pdf_bytes).decode("utf-8")
        user_content = [
            {
                "type": "document",
                "source": {
                    "type": "base64",
                    "media_type": "application/pdf",
                    "data": pdf_b64,
                },
            },
            {"type": "text", "text": prompt},
        ]
    else:
        from redact import redact_pii, restore_pii

        text = file_path.read_text()
        redacted_text, pii_mapping = redact_pii(text)
        if save_redacted and pii_mapping:
            raw_dir.mkdir(parents=True, exist_ok=True)
            redacted_path = raw_dir / f"{file_path.stem}_redacted{suffix}"
            redacted_path.write_text(redacted_text)
        user_content = [
            {"type": "text", "text": f"<document>\n{redacted_text}\n</document>"},
            {"type": "text", "text": prompt},
        ]

    response = client.messages.create(
        model=EXTRACTION_MODEL,
        max_tokens=8192,
        messages=[{"role": "user", "content": user_content}],
    )

    # Parse response
    if not response.content or not hasattr(response.content[0], "text"):
        raise ValueError("Empty or unexpected response from Claude API")
    response_text = extract_fenced_block(response.content[0].text)
    if pii_mapping:
        response_text = restore_pii(response_text, pii_mapping)
    data = json.loads(response_text)

    result = ExtractionResult(
        **data,
        source_file=file_path.name,
        extraction_method="api",
    )

    paths = _write_outputs(result, raw_dir=raw_dir, findings_dir=findings_dir)
    return result, paths


def extract_manual(
    json_text: str,
    source_file: str,
    raw_dir: Path | None = None,
    findings_dir: Path | None = None,
) -> tuple[ExtractionResult, dict[str, str]]:
    """Parse manually provided JSON from a Claude chat extraction."""
    data = json.loads(json_text)

    result = ExtractionResult(
        **data,
        source_file=source_file,
        extraction_method="manual",
    )

    paths = _write_outputs(result, raw_dir=raw_dir, findings_dir=findings_dir)
    return result, paths
