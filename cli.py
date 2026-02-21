"""Soma CLI - personal health data pipeline."""

import subprocess

import typer

from config import DB_PATH, DBT_DIR, RAW_DIR

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
        result, paths = extract_api(pdf_path)

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


if __name__ == "__main__":
    app()
