"""Pydantic schemas for extraction output and loading."""

from datetime import date, datetime
from pydantic import BaseModel, Field, field_validator


class BiomarkerRow(BaseModel):
    """A single biomarker measurement from a lab report."""

    report_date: date
    provider: str
    biomarker_name: str
    value: str = Field(description="Raw value as-is, including < or > prefixes")
    unit: str = ""
    reference_range_low: str | None = None
    reference_range_high: str | None = None
    loinc_code: str | None = None
    notes: str | None = None

    @field_validator("value", "unit", mode="before")
    @classmethod
    def coerce_null_to_empty(cls, v: str | None) -> str:
        return v if v is not None else ""


class DocumentMetadata(BaseModel):
    """Metadata about the source document."""

    report_type: str = Field(
        description="blood_panel, genetics, radiology, specialist, prescription, or other"
    )
    report_date: date | None = None
    provider: str | None = None
    tags: list[str] = Field(default_factory=list)
    baseline_candidates: list[str] = Field(
        default_factory=list,
        description="Permanent medical facts worth promoting to baseline",
    )


class ExtractionResult(BaseModel):
    """Complete output from a lab report extraction."""

    biomarkers: list[BiomarkerRow]
    document_summary: str
    metadata: DocumentMetadata
    source_file: str = Field(description="Original PDF filename")
    extracted_at: datetime = Field(default_factory=datetime.now)
    extraction_method: str = Field(
        default="api", description="'api' or 'manual'"
    )
