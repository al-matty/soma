"""Soma CLI - personal health data pipeline.

Commands:
    extract     Extract biomarkers from a PDF lab report (API or manual).
    load        Ingest extracted JSON files from data/raw/ into DuckDB.
    transform   Run dbt pipeline: seed, run, and snapshot.
    render      Generate profile markdown (snapshot, timeline, history) from dbt marts.
    update-baseline  Propose derived baseline updates via Claude.
    status      Show pipeline summary (report count, biomarker count, profile files).
    query       Run an arbitrary SQL query against the DuckDB database.
    reload      Delete all data for a source file and re-load from corrected JSON.
    reset       Delete the DuckDB database file to start fresh.
    run         Full pipeline: extract -> load -> transform -> render.

Usage:
    python cli.py --help                  Show all commands.
    python cli.py <command> --help        Show options for a specific command.
    python cli.py extract --help          Example: show extract options (--pdf, --method).
"""

import subprocess
import typer

from config import DB_PATH, DBT_DIR, PROFILE_DIR, RAW_DIR

app = typer.Typer(help="Soma - personal health data pipeline")


@app.command()
def load(
    db_path: str = typer.Option(str(DB_PATH), help="Path to DuckDB database"),
    raw_dir: str = typer.Option(str(RAW_DIR), help="Path to raw JSON directory"),
) -> None:
    """Load extracted JSON files into DuckDB."""
    from pathlib import Path

    from load import load_all

    stats = load_all(db_path=Path(db_path), raw_dir=Path(raw_dir))

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
    dbt_commands = [
        ["dbt", "seed"],
        ["dbt", "run"],
        ["dbt", "snapshot"],
    ]
    for cmd in dbt_commands:
        typer.echo(f"Running: {' '.join(cmd)}")
        result = subprocess.run(cmd, cwd=str(DBT_DIR), capture_output=True, text=True)
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
    from pathlib import Path

    from extract import extract_api, extract_manual

    if method == "api":
        if not pdf:
            typer.echo("Error: --pdf is required for API extraction")
            raise typer.Exit(1)
        pdf_path = Path(pdf)
        if not pdf_path.exists():
            typer.echo(f"Error: PDF not found: {pdf}")
            raise typer.Exit(1)
        typer.echo(f"Extracting from {pdf_path.name} via API...")
        result, paths = extract_api(pdf_path, save_redacted=save_redacted)

        if save_redacted:
            redacted_path = RAW_DIR / f"{pdf_path.stem}_redacted.pdf"
            if redacted_path.exists():
                typer.echo(f"Redacted: {redacted_path}")
            else:
                typer.echo("No redaction applied (profile/redact.yml missing or empty)")

    elif method == "manual":
        source_file = pdf or typer.prompt("Source PDF filename")
        typer.echo("Paste the JSON extraction below (end with Ctrl+D):")
        import sys

        json_text = sys.stdin.read()
        result, paths = extract_manual(json_text, source_file)

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

    paths = render_all()
    typer.echo(f"Rendered {len(paths)} profile files:")
    for p in paths:
        typer.echo(f"  {p}")


@app.command()
def update_baseline() -> None:
    """Propose updates to the derived baseline via Claude."""
    from baseline import get_latest_findings, propose_updates, show_diff

    baseline_path = PROFILE_DIR / "baseline.yml"
    current = baseline_path.read_text() if baseline_path.exists() else ""

    typer.echo("Analyzing latest findings...")
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

    con = duckdb.connect(str(DB_PATH), read_only=True)

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

    con.close()


@app.command()
def query(
    sql: str = typer.Argument(..., help="SQL query to run"),
) -> None:
    """Run a SQL query against the DuckDB database."""
    import duckdb

    con = duckdb.connect(str(DB_PATH), read_only=True)
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
    db_path: str = typer.Option(str(DB_PATH), help="Path to DuckDB database"),
    raw_dir: str = typer.Option(str(RAW_DIR), help="Path to raw JSON directory"),
) -> None:
    """Delete and re-load data for a specific source file."""
    from pathlib import Path

    import duckdb

    from load import delete_source, load_all

    con = duckdb.connect(str(db_path))
    rows_deleted = delete_source(con, source_file)
    con.close()

    if rows_deleted == 0:
        typer.echo(f"No existing data found for '{source_file}'")
    else:
        typer.echo(f"Deleted {rows_deleted} rows for '{source_file}'")

    stats = load_all(db_path=Path(db_path), raw_dir=Path(raw_dir))
    typer.echo(
        f"Re-loaded: {stats['files_loaded']} file(s), "
        f"{stats['rows_inserted']} rows inserted"
    )


@app.command()
def reset(
    db_path: str = typer.Option(str(DB_PATH), help="Path to DuckDB database"),
    yes: bool = typer.Option(False, "--yes", "-y", help="Skip confirmation prompt"),
) -> None:
    """Delete the DuckDB database and start fresh."""
    from pathlib import Path

    path = Path(db_path)
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
    """Run the full pipeline: extract -> load -> transform -> render."""
    # Extract (if PDF provided)
    if pdf:
        extract(pdf=pdf, method=method, save_redacted=save_redacted)
    else:
        typer.echo("No --pdf provided, skipping extraction")

    # Load
    load(db_path=str(DB_PATH), raw_dir=str(RAW_DIR))

    # Transform
    transform()

    # Render
    render()

    typer.echo("\nPipeline complete!")


if __name__ == "__main__":
    app()
