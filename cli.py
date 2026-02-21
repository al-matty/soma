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


if __name__ == "__main__":
    app()
