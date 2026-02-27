"""DuckDB loader - ingests extraction JSON into raw tables."""

import json
import uuid
from pathlib import Path

import duckdb

from config import DB_PATH, RAW_DIR
from schema import ExtractionResult


def ensure_raw_tables(con: duckdb.DuckDBPyConnection) -> None:
    """Create raw schema and tables if they don't exist."""
    con.execute("CREATE SCHEMA IF NOT EXISTS raw")
    con.execute("""
        CREATE TABLE IF NOT EXISTS raw.lab_results (
            id              VARCHAR PRIMARY KEY,
            source_file     VARCHAR NOT NULL,
            extracted_at    TIMESTAMP NOT NULL,
            extraction_method VARCHAR NOT NULL,
            report_date     DATE NOT NULL,
            provider        VARCHAR NOT NULL,
            biomarker_name_raw VARCHAR NOT NULL,
            value_raw       VARCHAR NOT NULL,
            unit_raw        VARCHAR NOT NULL,
            reference_range_low_raw  VARCHAR,
            reference_range_high_raw VARCHAR,
            loinc_code      VARCHAR,
            notes           VARCHAR
        )
    """)
    con.execute("""
        CREATE TABLE IF NOT EXISTS raw.documents (
            id              VARCHAR PRIMARY KEY,
            source_file     VARCHAR NOT NULL UNIQUE,
            report_date     DATE NOT NULL,
            provider        VARCHAR NOT NULL,
            report_type     VARCHAR NOT NULL,
            tags            VARCHAR,
            markdown_path   VARCHAR,
            biomarker_count INTEGER NOT NULL,
            extracted_at    TIMESTAMP NOT NULL,
            extraction_method VARCHAR NOT NULL
        )
    """)


def load_extraction(con: duckdb.DuckDBPyConnection, result: ExtractionResult) -> int:
    """Load a single ExtractionResult into DuckDB. Returns number of rows inserted."""
    # Check if already loaded (loading is idempotent by source_file -> known files will be skipped)
    existing = con.execute(
        "SELECT COUNT(*) FROM raw.documents WHERE source_file = ?",
        [result.source_file],
    ).fetchone()[0]
    if existing > 0:
        return 0

    # Insert document record
    report_date = result.biomarkers[0].report_date if result.biomarkers else None
    provider = result.biomarkers[0].provider if result.biomarkers else "unknown"
    year = str(report_date.year) if report_date else "unknown"
    md_path = f"docs/findings/{year}/{report_date}_{result.metadata.report_type}_{provider}.md"

    con.execute(
        """INSERT INTO raw.documents
           (id, source_file, report_date, provider, report_type, tags,
            markdown_path, biomarker_count, extracted_at, extraction_method)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
        [
            str(uuid.uuid4()),
            result.source_file,
            report_date,
            provider,
            result.metadata.report_type,
            ",".join(result.metadata.tags),
            md_path,
            len(result.biomarkers),
            result.extracted_at,
            result.extraction_method,
        ],
    )

    # Insert biomarker rows
    for row in result.biomarkers:
        con.execute(
            """INSERT INTO raw.lab_results
               (id, source_file, extracted_at, extraction_method, report_date,
                provider, biomarker_name_raw, value_raw, unit_raw,
                reference_range_low_raw, reference_range_high_raw, loinc_code, notes)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            [
                str(uuid.uuid4()),
                result.source_file,
                result.extracted_at,
                result.extraction_method,
                row.report_date,
                row.provider,
                row.biomarker_name,
                row.value,
                row.unit,
                row.reference_range_low,
                row.reference_range_high,
                row.loinc_code,
                row.notes,
            ],
        )

    return len(result.biomarkers)


def delete_source(con: duckdb.DuckDBPyConnection, source_file: str) -> int:
    """Delete all raw data for a given source_file. Returns rows deleted."""
    rows = con.execute(
        "SELECT COUNT(*) FROM raw.lab_results WHERE source_file = ?",
        [source_file],
    ).fetchone()[0]
    con.execute("DELETE FROM raw.lab_results WHERE source_file = ?", [source_file])
    con.execute("DELETE FROM raw.documents WHERE source_file = ?", [source_file])
    return rows


def load_all(db_path: Path = DB_PATH, raw_dir: Path = RAW_DIR) -> dict:
    """Load all JSON files from raw_dir into DuckDB. Returns summary stats."""
    json_files = sorted(raw_dir.glob("*.json"))
    if not json_files:
        return {"files_found": 0, "files_loaded": 0, "rows_inserted": 0}

    con = duckdb.connect(str(db_path))
    ensure_raw_tables(con)

    files_loaded = 0
    total_rows = 0
    errors = []
    for f in json_files:
        try:
            data = json.loads(f.read_text())
            result = ExtractionResult(**data)
            rows = load_extraction(con, result)
            if rows > 0:
                files_loaded += 1
                total_rows += rows
        except (json.JSONDecodeError, ValueError) as e:
            errors.append(f"{f.name}: {e}")

    con.close()
    return {
        "files_found": len(json_files),
        "files_loaded": files_loaded,
        "rows_inserted": total_rows,
        "errors": errors,
    }
