"""Minimal `felix` entrypoint. Package subcommands land here as they ship."""

from pathlib import Path

import typer

from felixs_common import LocationId

app = typer.Typer(help="Felix's Tools CLI")
logger_app = typer.Typer(help="Logger: ingest and search logs")
app.add_typer(logger_app, name="logger")


@app.callback()
def main() -> None:
    """Felix's Tools."""


@logger_app.command("ingest")
def logger_ingest(
    path: Path = typer.Argument(..., exists=True, readable=True, dir_okay=False),
    db: Path = typer.Option(Path(".felixs/logger.db"), "--db", help="SQLite index path"),
    service: str | None = typer.Option(None, "--service", help="Optional service label"),
    score: bool = typer.Option(False, "--score", help="Run anomaly scorer while ingesting"),
) -> None:
    """Ingest a log file into the structured index."""
    from felixs_logger import Logger

    location = LocationId(path=str(path), service=service)
    log = Logger(db)
    try:
        count = log.ingest_file(path, location=location, score=score)
    finally:
        log.close()
    typer.echo(f"ingested {count} lines into {db}")


@logger_app.command("search")
def logger_search(
    question: str = typer.Argument(..., help="Natural-language log question"),
    db: Path = typer.Option(Path(".felixs/logger.db"), "--db", help="SQLite index path"),
    limit: int = typer.Option(20, "--limit", min=1),
) -> None:
    """Search the index using the query planner."""
    from felixs_logger import Logger

    log = Logger(db)
    try:
        results = log.search(question)[:limit]
    finally:
        log.close()
    if not results:
        typer.echo("no matches")
        raise typer.Exit(code=0)
    for entry in results:
        loc = entry.location_key or "-"
        sev = entry.severity or "-"
        typer.echo(f"[{entry.id}] sev={sev} loc={loc} :: {entry.raw}")


if __name__ == "__main__":
    app()
