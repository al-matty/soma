"""Tests for the markdown renderer.

Builds a minimal in-memory DuckDB with the mart tables the render functions
query, so the rendering logic (trends, status, null handling, grouping) is
exercised without running dbt.
"""

import duckdb
import pytest

from render import (
    render_current_snapshot,
    render_medical_history,
    render_report_index,
    render_timeline,
)

FCT_COLUMNS = """
    biomarker_key VARCHAR, value_si DOUBLE, unit_si VARCHAR,
    value_original DOUBLE, unit_original VARCHAR, report_date DATE,
    provider VARCHAR, category VARCHAR, is_within_ref_range BOOLEAN,
    is_within_optimal_range BOOLEAN, is_below_detection_limit BOOLEAN,
    source_file VARCHAR
"""

DIM_COLUMNS = """
    report_date DATE, provider VARCHAR, report_type VARCHAR,
    source_file VARCHAR, biomarker_count INTEGER, tags VARCHAR,
    markdown_path VARCHAR
"""


@pytest.fixture
def con():
    """In-memory DuckDB with empty fct_biomarkers and dim_documents tables."""
    c = duckdb.connect(":memory:")
    c.execute(f"CREATE TABLE fct_biomarkers ({FCT_COLUMNS})")
    c.execute(f"CREATE TABLE dim_documents ({DIM_COLUMNS})")
    yield c
    c.close()


def _add_biomarker(con, **cols):
    """Insert one fct_biomarkers row, defaulting unspecified columns to NULL."""
    keys = list(cols)
    placeholders = ", ".join("?" for _ in keys)
    con.execute(
        f"INSERT INTO fct_biomarkers ({', '.join(keys)}) VALUES ({placeholders})",
        [cols[k] for k in keys],
    )


def test_snapshot_trend_and_optimal_status(con):
    """Two dated readings produce an up-trend and 'Optimal' status."""
    for date_str, value in [("2025-01-01", 50.0), ("2025-06-01", 80.0)]:
        _add_biomarker(
            con, biomarker_key="Vitamin D", value_si=value, unit_si="nmol/L",
            value_original=value, unit_original="nmol/L", report_date=date_str,
            provider="Quest", category="vitamins", is_within_ref_range=True,
            is_within_optimal_range=True, is_below_detection_limit=False,
            source_file="a.pdf",
        )

    out = render_current_snapshot(con)

    assert "| Vitamin D |" in out
    assert "Optimal" in out
    assert "^" in out  # 60% increase is an up-trend


def test_snapshot_null_original_renders_dash(con):
    """A row with NULL value_original renders '-', never the literal 'None'."""
    _add_biomarker(
        con, biomarker_key="IL-6", value_si=None, unit_si=None,
        value_original=None, unit_original=None, report_date="2025-06-01",
        provider="Quest", category="immune", is_within_ref_range=None,
        is_within_optimal_range=None, is_below_detection_limit=False,
        source_file="a.pdf",
    )

    out = render_current_snapshot(con)

    assert "| IL-6 |" in out
    assert "None" not in out


def test_timeline_lists_reports(con):
    """Timeline reports every document with a total count."""
    con.execute(
        "INSERT INTO dim_documents VALUES "
        "('2025-01-01', 'Quest', 'blood_panel', 'a.pdf', 6, 'fasting', 'p/a.md'), "
        "('2025-06-01', 'Labcorp', 'blood_panel', 'b.pdf', 5, NULL, 'p/b.md')"
    )

    out = render_timeline(con)

    assert "Total reports: 2" in out
    assert "Quest" in out and "Labcorp" in out
    assert "[fasting]" in out  # tags rendered when present


def test_medical_history_null_derived_section(con, tmp_path, monkeypatch):
    """A baseline.yml with an empty 'derived:' key does not crash rendering."""
    monkeypatch.setattr("render.PROFILE_DIR", tmp_path)
    (tmp_path / "baseline.yml").write_text("derived:\n")

    out = render_medical_history(con)

    assert out.startswith("# Medical History")


def test_medical_history_renders_conditions(con, tmp_path, monkeypatch):
    """Conditions from baseline.yml are grouped under their status heading."""
    monkeypatch.setattr("render.PROFILE_DIR", tmp_path)
    (tmp_path / "baseline.yml").write_text(
        "derived:\n"
        "  conditions:\n"
        "    - name: Vitamin D deficiency\n"
        "      status: active\n"
        "      details: Supplementing 4000 IU daily\n"
    )

    out = render_medical_history(con)

    assert "## Conditions" in out
    assert "### Active" in out
    assert "**Vitamin D deficiency**" in out


def test_medical_history_no_baseline(con, tmp_path, monkeypatch):
    """Missing baseline.yml yields the setup hint instead of crashing."""
    monkeypatch.setattr("render.PROFILE_DIR", tmp_path)

    out = render_medical_history(con)

    assert "No baseline profile found" in out


def test_report_index_counts_out_of_range(con):
    """Report index reports the out-of-range biomarker count per document."""
    con.execute(
        "INSERT INTO dim_documents VALUES "
        "('2025-06-01', 'Quest', 'blood_panel', 'a.pdf', 2, NULL, "
        "'docs/findings/2025/a.md')"
    )
    _add_biomarker(
        con, biomarker_key="Glucose", value_si=5.0, report_date="2025-06-01",
        is_within_ref_range=True, source_file="a.pdf",
    )
    _add_biomarker(
        con, biomarker_key="LDL", value_si=4.5, report_date="2025-06-01",
        is_within_ref_range=False, source_file="a.pdf",
    )

    out = render_report_index(con)

    assert "Total reports: 1" in out
    # Two-biomarker doc with exactly one out-of-range reading
    assert "| 2 | 1 |" in out
