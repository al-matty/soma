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


def _write_outputs(result: ExtractionResult) -> dict[str, str]:
    """Write JSON and markdown outputs. Returns paths written."""
    # Determine filenames from extraction data
    report_date = result.biomarkers[0].report_date if result.biomarkers else "unknown"
    provider = result.biomarkers[0].provider if result.biomarkers else "unknown"
    provider_slug = re.sub(r"[^a-z0-9]+", "_", provider.lower()).strip("_")
    timestamp = datetime.now().strftime("%H%M%S")

    # Write JSON to data/raw/
    RAW_DIR.mkdir(parents=True, exist_ok=True)
    json_filename = f"{report_date}_{provider_slug}_{timestamp}.json"
    json_path = RAW_DIR / json_filename
    json_path.write_text(result.model_dump_json(indent=2))

    # Write markdown to docs/findings/YYYY/
    year = str(report_date)[:4] if str(report_date) != "unknown" else "unknown"
    findings_year_dir = FINDINGS_DIR / year
    findings_year_dir.mkdir(parents=True, exist_ok=True)
    report_type = result.metadata.report_type
    md_filename = f"{report_date}_{report_type}_{provider_slug}.md"
    md_path = findings_year_dir / md_filename
    md_path.write_text(result.document_summary)

    return {"json_path": str(json_path), "markdown_path": str(md_path)}


def extract_api(pdf_path: Path, save_redacted: bool = False) -> tuple[ExtractionResult, dict[str, str]]:
    """Extract biomarkers from a PDF via Claude API."""
    import anthropic

    if not ANTHROPIC_API_KEY:
        raise ValueError(
            "ANTHROPIC_API_KEY not set. Export it or add to .env file."
        )

    client = anthropic.Anthropic(api_key=ANTHROPIC_API_KEY)
    prompt = _read_prompt()

    # Read and encode PDF (with PII redaction if configured)
    pdf_bytes, was_redacted = _redact_pdf(pdf_path)

    if save_redacted and was_redacted:
        RAW_DIR.mkdir(parents=True, exist_ok=True)
        redacted_path = RAW_DIR / f"{pdf_path.stem}_redacted.pdf"
        redacted_path.write_bytes(pdf_bytes)
    pdf_b64 = base64.b64encode(pdf_bytes).decode("utf-8")

    response = client.messages.create(
        model=EXTRACTION_MODEL,
        max_tokens=8192,
        messages=[
            {
                "role": "user",
                "content": [
                    {
                        "type": "document",
                        "source": {
                            "type": "base64",
                            "media_type": "application/pdf",
                            "data": pdf_b64,
                        },
                    },
                    {"type": "text", "text": prompt},
                ],
            }
        ],
    )

    # Parse response
    if not response.content or not hasattr(response.content[0], "text"):
        raise ValueError("Empty or unexpected response from Claude API")
    response_text = response.content[0].text
    # Strip markdown code fences if present
    response_text = re.sub(r"^```(?:json)?\s*\n?", "", response_text)
    response_text = re.sub(r"\n?```\s*$", "", response_text)
    data = json.loads(response_text)

    result = ExtractionResult(
        **data,
        source_file=pdf_path.name,
        extraction_method="api",
    )

    paths = _write_outputs(result)
    return result, paths


def extract_manual(json_text: str, source_file: str) -> tuple[ExtractionResult, dict[str, str]]:
    """Parse manually provided JSON from a Claude chat extraction."""
    data = json.loads(json_text)

    result = ExtractionResult(
        **data,
        source_file=source_file,
        extraction_method="manual",
    )

    paths = _write_outputs(result)
    return result, paths
