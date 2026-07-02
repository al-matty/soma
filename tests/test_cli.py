"""Tests for CLI commands, focused on `compare`.

Builds tiny DuckDB files holding an fct_biomarkers table (matching how dbt
materializes the mart) and drives the command through Typer's CliRunner.
"""

import duckdb
import pytest
from typer.testing import CliRunner

import cli

runner = CliRunner()


def _make_fct_db(path, rows):
    """Create a DuckDB file with an fct_biomarkers table holding `rows`."""
    path.parent.mkdir(parents=True, exist_ok=True)
    con = duckdb.connect(str(path))
    con.execute("""
        CREATE TABLE fct_biomarkers (
            biomarker_key VARCHAR, report_date DATE, value_si DOUBLE,
            unit_si VARCHAR, source_file VARCHAR
        )
    """)
    for r in rows:
        con.execute("INSERT INTO fct_biomarkers VALUES (?, ?, ?, ?, ?)", r)
    con.close()


@pytest.fixture
def wired(tmp_path, monkeypatch):
    """Point cli's production and env DB paths into a temp tree."""
    data_dir = tmp_path / "data"
    prod_db = data_dir / "soma.duckdb"
    monkeypatch.setattr(cli, "DATA_DIR", data_dir)
    monkeypatch.setattr(cli, "DB_PATH", prod_db)
    return data_dir, prod_db


def _env_db(data_dir, env):
    return data_dir / "envs" / env / "soma.duckdb"


def test_compare_no_differences(wired):
    data_dir, prod_db = wired
    rows = [("Glucose", "2025-06-01", 5.0, "mmol/L", "a.pdf")]
    _make_fct_db(prod_db, rows)
    _make_fct_db(_env_db(data_dir, "exp"), rows)

    result = runner.invoke(cli.app, ["compare", "exp"])

    assert result.exit_code == 0
    assert "No differences found." in result.stdout


def test_compare_detects_null_change(wired):
    """A value that becomes NULL in the env is reported (IS DISTINCT FROM)."""
    data_dir, prod_db = wired
    _make_fct_db(prod_db, [("Glucose", "2025-06-01", 5.0, "mmol/L", "a.pdf")])
    _make_fct_db(_env_db(data_dir, "exp"), [("Glucose", "2025-06-01", None, "mmol/L", "a.pdf")])

    result = runner.invoke(cli.app, ["compare", "exp"])

    assert result.exit_code == 0
    assert "CHANGED" in result.stdout
    assert "Glucose" in result.stdout


def test_compare_source_file_filter_with_quote(wired):
    """A --source-file value containing a quote is bound safely, not interpolated."""
    data_dir, prod_db = wired
    rows = [("Glucose", "2025-06-01", 5.0, "mmol/L", "o'brien.pdf")]
    _make_fct_db(prod_db, rows)
    _make_fct_db(_env_db(data_dir, "exp"), rows)

    result = runner.invoke(cli.app, ["compare", "exp", "--source-file", "o'brien.pdf"])

    assert result.exit_code == 0
    assert "No differences found." in result.stdout


def test_compare_missing_env_exits_nonzero(wired):
    data_dir, prod_db = wired
    _make_fct_db(prod_db, [("Glucose", "2025-06-01", 5.0, "mmol/L", "a.pdf")])

    result = runner.invoke(cli.app, ["compare", "does-not-exist"])

    assert result.exit_code == 1
    assert "Environment database not found" in result.stdout
