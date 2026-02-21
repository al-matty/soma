"""Tests for the DuckDB loader."""

import json
from pathlib import Path

import duckdb
import pytest

from load import ensure_raw_tables, load_all, load_extraction
from schema import ExtractionResult

FIXTURES_DIR = Path(__file__).parent / "fixtures"


@pytest.fixture
def tmp_db(tmp_path):
    """Create a temporary DuckDB database with raw tables."""
    db_path = tmp_path / "test.duckdb"
    con = duckdb.connect(str(db_path))
    ensure_raw_tables(con)
    con.close()
    return db_path


@pytest.fixture
def sample_result():
    """Load the Quest fixture as an ExtractionResult."""
    data = json.loads((FIXTURES_DIR / "2025-11-15_blood_panel_quest.json").read_text())
    return ExtractionResult(**data)


def test_load_single_extraction(tmp_db, sample_result):
    """Loading a single extraction inserts correct row counts."""
    con = duckdb.connect(str(tmp_db))
    ensure_raw_tables(con)
    rows = load_extraction(con, sample_result)
    assert rows == 6

    lab_count = con.execute("SELECT COUNT(*) FROM raw.lab_results").fetchone()[0]
    doc_count = con.execute("SELECT COUNT(*) FROM raw.documents").fetchone()[0]
    assert lab_count == 6
    assert doc_count == 1
    con.close()


def test_load_idempotent(tmp_db, sample_result):
    """Re-loading the same file inserts zero rows."""
    con = duckdb.connect(str(tmp_db))
    ensure_raw_tables(con)
    load_extraction(con, sample_result)
    rows = load_extraction(con, sample_result)
    assert rows == 0

    lab_count = con.execute("SELECT COUNT(*) FROM raw.lab_results").fetchone()[0]
    assert lab_count == 6
    con.close()


def test_load_queryable(tmp_db, sample_result):
    """Loaded data is queryable with correct values."""
    con = duckdb.connect(str(tmp_db))
    ensure_raw_tables(con)
    load_extraction(con, sample_result)

    # Check a specific biomarker value
    result = con.execute(
        "SELECT value_raw, unit_raw FROM raw.lab_results WHERE biomarker_name_raw = 'Vitamin D (25-OH)'"
    ).fetchone()
    assert result == ("22", "ng/mL")

    # Check detection limit value preserved
    result = con.execute(
        "SELECT value_raw FROM raw.lab_results WHERE biomarker_name_raw = 'CRP (hs)'"
    ).fetchone()
    assert result[0] == "<0.1"
    con.close()


def test_load_all_fixtures(tmp_path):
    """load_all processes all fixture files."""
    db_path = tmp_path / "test.duckdb"
    stats = load_all(db_path=db_path, raw_dir=FIXTURES_DIR)

    assert stats["files_found"] == 3
    assert stats["files_loaded"] == 3
    assert stats["rows_inserted"] == 13  # 6 + 5 + 2

    # Verify idempotency of load_all
    stats2 = load_all(db_path=db_path, raw_dir=FIXTURES_DIR)
    assert stats2["files_loaded"] == 0
    assert stats2["rows_inserted"] == 0
