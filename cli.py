"""Soma CLI - personal health data pipeline.

Commands:
    extract     Extract biomarkers from a PDF lab report (API or manual).
    load        Ingest extracted JSON files from data/raw/ into DuckDB.
    transform   Run dbt pipeline: seed, run, and snapshot.
    render      Generate profile markdown (snapshot, timeline, history, report index) from dbt marts.
    update-baseline  Propose derived baseline updates via Claude.
    status      Show pipeline status summary.
    query       Run an arbitrary SQL query against the DuckDB database.
    reload      Delete all data for a source file and re-load from corrected JSON.
    reset       Delete the DuckDB database file to start fresh.
    run         Full pipeline: extract -> load -> transform -> render.
    compare     Compare biomarkers between an environment and production.

Usage:
    python cli.py --help                  Show all commands.
    python cli.py <command> --help        Show options for a specific command.
    python cli.py --env test extract ...  Run in a named environment.
"""

import os
import subprocess
from pathlib import Path

import typer

from config import DATA_DIR, DB_PATH, DBT_DIR, FINDINGS_DIR, PROFILE_DIR, RAW_DIR

app = typer.Typer(help="Soma - personal health data pipeline")

# --- Environment isolation ---

_env_name: str | None = None


def _db_path() -> Path:
    if _env_name:
        return DATA_DIR / "envs" / _env_name / "soma.duckdb"
    return DB_PATH


def _raw_dir() -> Path:
    if _env_name:
        return DATA_DIR / "envs" / _env_name / "raw"
    return RAW_DIR


def _findings_dir() -> Path:
    if _env_name:
        return DATA_DIR / "envs" / _env_name / "findings"
    return FINDINGS_DIR


@app.callback()
def main(
    env: str = typer.Option(None, "--env", help="Named environment for isolated pipeline runs (e.g. --env test)"),
) -> None:
    """Soma - personal health data pipeline."""
    global _env_name
    _env_name = env
    if env:
        _raw_dir().mkdir(parents=True, exist_ok=True)


# --- Commands ---


@app.command()
def load() -> None:
    """Load extracted JSON files into DuckDB.

    Idempotent by source file: JSON files whose source PDF has already been loaded are
    skipped automatically. It is safe to leave all files in data/raw/ permanently.
    """
    from load import load_all

    db_path = _db_path()
    raw_dir = _raw_dir()
    stats = load_all(db_path=db_path, raw_dir=raw_dir)

    if stats["files_found"] == 0:
        typer.echo(f"No JSON files found in {raw_dir}")
        raise typer.Exit(1)

    typer.echo(
        f"Found {stats['files_found']} file(s), "
        f"loaded {stats['files_loaded']} new, "
        f"{stats['rows_inserted']} biomarker rows inserted"
    )
    for err in stats.get("errors", []):
        typer.echo(f"  Error: {err}", err=True)


@app.command()
def transform() -> None:
    """Run dbt pipeline: seed, run, and snapshot."""
    dbt_env = os.environ.copy()
    if _env_name:
        # Relative to dbt_project/ (which is where dbt runs)
        dbt_env["SOMA_DB_PATH"] = str(
            Path("..") / "data" / "envs" / _env_name / "soma.duckdb"
        )

    dbt_commands = [
        ["dbt", "seed"],
        ["dbt", "run"],
        ["dbt", "snapshot"],
    ]
    for cmd in dbt_commands:
        typer.echo(f"Running: {' '.join(cmd)}")
        result = subprocess.run(cmd, cwd=str(DBT_DIR), capture_output=True, text=True, env=dbt_env)
        if result.returncode != 0:
            typer.echo(result.stdout)
            typer.echo(result.stderr)
            raise typer.Exit(1)
    typer.echo("Transform complete")


@app.command()
def extract(
    pdf: str = typer.Option(None, help="Path to PDF lab report"),
    method: str = typer.Option("api", help="Extraction method: 'api' or 'manual'"),
    save_redacted: bool = typer.Option(False, "--save-redacted", help="Save redacted PDF to data/raw/ for visual verification"),
) -> None:
    """Extract biomarkers from a lab report PDF."""
    from extract import extract_api, extract_manual

    raw_dir = _raw_dir()
    findings_dir = _findings_dir()

    if method == "api":
        if not pdf:
            typer.echo("Error: --pdf is required for API extraction")
            raise typer.Exit(1)
        pdf_path = Path(pdf)
        if not pdf_path.exists():
            typer.echo(f"Error: PDF not found: {pdf}")
            raise typer.Exit(1)
        typer.echo(f"Extracting from {pdf_path.name} via API...")
        result, paths = extract_api(
            pdf_path, save_redacted=save_redacted,
            raw_dir=raw_dir, findings_dir=findings_dir,
        )

        if save_redacted:
            redacted_path = raw_dir / f"{pdf_path.stem}_redacted.pdf"
            if redacted_path.exists():
                typer.echo(f"Redacted: {redacted_path}")
            else:
                typer.echo("No redaction applied (profile/redact.yml missing or empty)")

    elif method == "manual":
        source_file = pdf or typer.prompt("Source PDF filename")
        typer.echo("Paste the JSON extraction below (end with Ctrl+D):")
        import sys

        json_text = sys.stdin.read()
        result, paths = extract_manual(
            json_text, source_file,
            raw_dir=raw_dir, findings_dir=findings_dir,
        )

    else:
        typer.echo(f"Error: unknown method '{method}'. Use 'api' or 'manual'.")
        raise typer.Exit(1)

    typer.echo(f"Extracted {len(result.biomarkers)} biomarkers")
    typer.echo(f"JSON:     {paths['json_path']}")
    typer.echo(f"Markdown: {paths['markdown_path']}")


@app.command()
def render() -> None:
    """Generate profile markdown from dbt marts."""
    from render import render_all

    paths = render_all(db_path=_db_path())
    typer.echo(f"Rendered {len(paths)} profile files:")
    for p in paths:
        typer.echo(f"  {p}")


@app.command()
def update_baseline() -> None:
    """Propose updates to the derived baseline via Claude."""
    from baseline import get_latest_findings, propose_updates, show_diff

    baseline_path = PROFILE_DIR / "baseline.yml"
    current = baseline_path.read_text() if baseline_path.exists() else ""

    typer.echo("Analyzing latest findings...\n")
    proposed = propose_updates()

    if proposed is None:
        typer.echo("ANTHROPIC_API_KEY not set. Cannot propose updates.")
        raise typer.Exit(1)

    diff = show_diff(current, proposed)
    typer.echo("\nProposed changes:")
    typer.echo(diff)

    if diff == "(no changes)":
        typer.echo("\nNo updates needed.")
        return

    if typer.confirm("\nApply these changes?"):
        baseline_path.parent.mkdir(parents=True, exist_ok=True)
        baseline_path.write_text(proposed)
        typer.echo(f"Updated {baseline_path}")
    else:
        typer.echo("Changes discarded.")


@app.command()
def status() -> None:
    """Show pipeline status summary."""
    import duckdb

    db_path = _db_path()
    con = duckdb.connect(str(db_path), read_only=True)

    try:
        docs = con.execute("SELECT COUNT(*), MIN(report_date), MAX(report_date) FROM raw.documents").fetchone()
        biomarkers = con.execute("SELECT COUNT(DISTINCT biomarker_name_raw) FROM raw.lab_results").fetchone()
        rows = con.execute("SELECT COUNT(*) FROM raw.lab_results").fetchone()
    except duckdb.CatalogException:
        typer.echo("No data loaded yet. Run 'soma load' first.")
        raise typer.Exit(1)

    typer.echo(f"Reports:    {docs[0]} ({docs[1]} to {docs[2]})")
    typer.echo(f"Biomarkers: {biomarkers[0]} unique, {rows[0]} total measurements")

    # Check profile files
    profile_files = ["baseline.yml", "lifestyle.yml", "supplements.yml", "medications.yml", "experiments.yml"]
    existing = [f for f in profile_files if (PROFILE_DIR / f).exists()]
    typer.echo(f"Profile:    {len(existing)}/{len(profile_files)} files configured")

    if _env_name:
        typer.echo(f"Environment: {_env_name}")

    con.close()


@app.command()
def query(
    sql: str = typer.Argument(..., help="SQL query to run"),
) -> None:
    """Run a SQL query against the DuckDB database."""
    import duckdb

    con = duckdb.connect(str(_db_path()), read_only=True)
    try:
        result = con.sql(sql)
        result.show()
    except duckdb.Error as e:
        typer.echo(f"Error: {e}", err=True)
        raise typer.Exit(1)
    finally:
        con.close()


@app.command()
def reload(
    source_file: str = typer.Argument(..., help="source_file value to reload (original PDF filename)"),
) -> None:
    """Delete and re-load data for a specific source file."""
    import duckdb

    from load import delete_source, load_all

    db_path = _db_path()
    raw_dir = _raw_dir()

    con = duckdb.connect(str(db_path))
    rows_deleted = delete_source(con, source_file)
    con.close()

    if rows_deleted == 0:
        typer.echo(f"No existing data found for '{source_file}'")
    else:
        typer.echo(f"Deleted {rows_deleted} rows for '{source_file}'")

    stats = load_all(db_path=db_path, raw_dir=raw_dir)
    typer.echo(
        f"Re-loaded: {stats['files_loaded']} file(s), "
        f"{stats['rows_inserted']} rows inserted"
    )


@app.command()
def reset(
    yes: bool = typer.Option(False, "--yes", "-y", help="Skip confirmation prompt"),
) -> None:
    """Delete the DuckDB database and start fresh."""
    path = _db_path()
    if not path.exists():
        typer.echo("No database found. Nothing to reset.")
        return

    if not yes:
        typer.confirm(f"Delete {path}?", abort=True)

    path.unlink()
    typer.echo(f"Deleted {path}")


@app.command()
def run(
    pdf: str = typer.Option(None, help="Path to PDF lab report"),
    method: str = typer.Option("api", help="Extraction method: 'api' or 'manual'"),
    save_redacted: bool = typer.Option(False, "--save-redacted", help="Save redacted PDF to data/raw/ for visual verification"),
) -> None:
    """Run the full pipeline: extract -> load -> transform -> render.

    Without --pdf, skips extraction and runs load -> transform -> render on existing
    JSON files in data/raw/. Useful for reprocessing after editing JSON or dbt models.
    """
    # Extract (if PDF provided)
    if pdf:
        extract(pdf=pdf, method=method, save_redacted=save_redacted)
    else:
        typer.echo("No --pdf provided, skipping extraction")

    # Load
    load()

    # Transform
    transform()

    # Render
    render()

    typer.echo("\nPipeline complete!")


@app.command()
def compare(
    env: str = typer.Argument(..., help="Environment name to compare against production"),
    source_file: str = typer.Option(None, "--source-file", help="Filter to a specific source file"),
) -> None:
    """Compare biomarkers between a named environment and production."""
    import duckdb

    env_db = DATA_DIR / "envs" / env / "soma.duckdb"
    if not env_db.exists():
        typer.echo(f"Environment database not found: {env_db}")
        raise typer.Exit(1)
    if not DB_PATH.exists():
        typer.echo(f"Production database not found: {DB_PATH}")
        raise typer.Exit(1)

    con = duckdb.connect(":memory:")
    con.execute(f"ATTACH '{DB_PATH}' AS prod (READ_ONLY)")
    con.execute(f"ATTACH '{env_db}' AS env (READ_ONLY)")

    where_clause = ""
    if source_file:
        where_clause = f"AND (p.source_file = '{source_file}' OR d.source_file = '{source_file}')"

    # Summary counts
    prod_count = con.execute("SELECT count(*) FROM prod.main.fct_biomarkers").fetchone()[0]
    env_count = con.execute("SELECT count(*) FROM env.main.fct_biomarkers").fetchone()[0]
    typer.echo(f"Production: {prod_count} biomarker rows")
    typer.echo(f"Environment '{env}': {env_count} biomarker rows")
    typer.echo("")

    # Diff
    result = con.sql(f"""
        SELECT
            coalesce(p.biomarker_key, d.biomarker_key) as biomarker,
            coalesce(p.report_date, d.report_date) as report_date,
            p.value_si as prod_value,
            d.value_si as env_value,
            round(d.value_si - p.value_si, 4) as diff,
            coalesce(p.unit_si, d.unit_si) as unit,
            case
                when p.biomarker_key is null then 'ENV ONLY'
                when d.biomarker_key is null then 'PROD ONLY'
                when p.value_si != d.value_si then 'CHANGED'
                else 'SAME'
            end as status
        FROM prod.main.fct_biomarkers p
        FULL OUTER JOIN env.main.fct_biomarkers d
            ON p.biomarker_key = d.biomarker_key
            AND p.report_date = d.report_date
        WHERE (p.value_si != d.value_si
            OR p.biomarker_key IS NULL
            OR d.biomarker_key IS NULL)
            {where_clause}
        ORDER BY report_date, biomarker
    """)

    if result.shape[0] == 0:
        typer.echo("No differences found.")
    else:
        typer.echo(f"Differences ({result.shape[0]} rows):")
        result.show(max_rows=100)

    con.close()


if __name__ == "__main__":
    app()
