"""Soma CLI - personal health data pipeline."""

import typer

from config import DB_PATH, RAW_DIR

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


if __name__ == "__main__":
    app()
