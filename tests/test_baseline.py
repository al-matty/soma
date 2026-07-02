"""Tests for the baseline updater's pure and read-only helpers.

propose_updates() calls the Claude API and is not covered here; the response
parsing it relies on is tested via extract_fenced_block in test_extract.py.
"""

import duckdb
import pytest

from baseline import get_latest_findings, show_diff


def _make_marts_db(tmp_path, biomarkers=(), docs=()):
    """Create a DuckDB file with fct_biomarkers and dim_documents populated."""
    db_path = tmp_path / "marts.duckdb"
    con = duckdb.connect(str(db_path))
    con.execute("""
        CREATE TABLE fct_biomarkers (
            biomarker_key VARCHAR, value_raw VARCHAR, value_si DOUBLE,
            unit_si VARCHAR, report_date DATE, provider VARCHAR,
            is_within_ref_range BOOLEAN, is_within_optimal_range BOOLEAN,
            category VARCHAR
        )
    """)
    con.execute("""
        CREATE TABLE dim_documents (
            report_date DATE, provider VARCHAR, report_type VARCHAR,
            source_file VARCHAR, document_summary VARCHAR,
            baseline_candidates VARCHAR
        )
    """)
    for b in biomarkers:
        con.execute(
            "INSERT INTO fct_biomarkers VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)", b
        )
    for d in docs:
        con.execute("INSERT INTO dim_documents VALUES (?, ?, ?, ?, ?, ?)", d)
    con.close()
    return db_path


def test_show_diff_reports_changes():
    """show_diff surfaces added and removed lines."""
    diff = show_diff("a: 1\nb: 2", "a: 1\nb: 3")
    assert "-b: 2" in diff
    assert "+b: 3" in diff


def test_show_diff_no_changes():
    """Identical inputs report no changes."""
    assert show_diff("a: 1", "a: 1") == "(no changes)"


def test_get_latest_findings_empty(tmp_path):
    """Empty marts yield the no-data sentinel."""
    db_path = _make_marts_db(tmp_path)
    assert get_latest_findings(db_path=db_path) == "No findings data found."


def test_get_latest_findings_formats_rows(tmp_path):
    """Findings text includes the biomarker and its in-range verdict."""
    db_path = _make_marts_db(
        tmp_path,
        biomarkers=[
            ("Glucose", "90", 5.0, "mmol/L", "2025-06-01", "Quest", True, True, "metabolic"),
            ("LDL", "180", 4.65, "mmol/L", "2025-06-01", "Quest", False, False, "lipids"),
        ],
        docs=[
            ("2025-06-01", "Quest", "blood_panel", "a.pdf", "Routine panel.", None),
        ],
    )

    out = get_latest_findings(db_path=db_path)

    assert "Glucose" in out and "in range" in out
    assert "LDL" in out and "OUT OF RANGE" in out
    assert "Routine panel." in out
