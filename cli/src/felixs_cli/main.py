"""Minimal `felix` entrypoint. Package subcommands land here as they ship."""

import json
from pathlib import Path

import typer
from common import LocationId

app = typer.Typer(help="Felix's Tools CLI")
logger_app = typer.Typer(help="Logger: ingest and search logs")
app.add_typer(logger_app, name="logger")


@app.callback()
def main() -> None:
    """Felix's Tools."""


@logger_app.command("ingest")
def logger_ingest(
    path: Path = typer.Argument(..., exists=True, readable=True, dir_okay=False),
    db: Path = typer.Option(Path(".felix-tools/logger.db"), "--db", help="SQLite index path"),
    service: str | None = typer.Option(None, "--service", help="Optional service label"),
    score: bool = typer.Option(False, "--score", help="Run anomaly scorer while ingesting"),
) -> None:
    """Ingest a log file into the structured index."""
    from logger import Logger

    location = LocationId(path=str(path), service=service)
    log = Logger(db)
    try:
        count = log.ingest_file(path, location=location, score=score)
    finally:
        log.close()
    typer.echo(f"ingested {count} lines into {db}")


@logger_app.command("ingest-corpus")
def logger_ingest_corpus(
    dataset: str = typer.Option(..., "--dataset", help="LogHub dataset name"),
    source: Path = typer.Option(..., "--source", exists=True, readable=True),
    out: Path = typer.Option(..., "--out", help="Corpus SQLite path"),
    sample: int | None = typer.Option(None, "--sample", help="Sample size; omit for full ingest"),
    seed: int | None = typer.Option(None, "--seed", help="Sampling seed"),
    require_publishable: bool = typer.Option(
        False, "--require-publishable", help="Refuse datasets whose licence blocks derived data"
    ),
) -> None:
    """Build a reproducible corpus database from a staged LogHub dataset."""
    from logger.corpora import DEFAULT_SEED, dataset_names, ingest_loghub

    known = dataset_names()
    if dataset not in known:
        typer.echo(f"unknown dataset {dataset!r}; expected one of {', '.join(known)}", err=True)
        raise typer.Exit(2)

    try:
        manifest = ingest_loghub(
            dataset,
            source=source,
            out=out,
            sample_size=sample,
            seed=DEFAULT_SEED if seed is None else seed,
            require_publishable=require_publishable,
        )
    except PermissionError as exc:
        typer.echo(str(exc), err=True)
        raise typer.Exit(3) from exc

    typer.echo(
        f"ingested {manifest.row_count} rows ({manifest.template_count} templates) into {out}\n"
        f"digest={manifest.content_digest}"
    )


@logger_app.command("search")
def logger_search(
    question: str = typer.Argument(..., help="Natural-language log question"),
    db: Path = typer.Option(Path(".felix-tools/logger.db"), "--db", help="SQLite index path"),
    limit: int = typer.Option(20, "--limit", min=1),
) -> None:
    """Search the index using the query planner."""
    from logger import Logger

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


@logger_app.command("query")
def logger_query(
    plan: str = typer.Option(..., "--plan", help="Query plan as JSON, or @path to read a file"),
    db: Path = typer.Option(Path(".felix-tools/logger.db"), "--db", help="SQLite index path"),
    as_json: bool = typer.Option(False, "--json", help="Emit results as JSON"),
) -> None:
    """Execute a query plan against the index. Exits 2 if the plan is invalid."""
    from logger import Logger, validate_plan

    payload = Path(plan[1:]).read_text(encoding="utf-8") if plan.startswith("@") else plan
    validation = validate_plan(payload)
    if not validation.ok or validation.plan is None:
        _echo_errors(validation, as_json=as_json)
        raise typer.Exit(code=2)

    log = Logger(db)
    try:
        result = log.execute_plan(validation.plan)
    finally:
        log.close()

    if as_json:
        typer.echo(
            json.dumps(
                {
                    "row_ids": result.row_ids,
                    "rows": [vars(r) for r in result.rows],
                    "groups": [{"key": g.key, "count": g.count} for g in result.groups],
                    "rows_scanned": result.rows_scanned,
                    "query_count": result.query_count,
                },
                indent=2,
            )
        )
        return

    for entry in result.rows:
        loc = entry.location_key or "-"
        sev = entry.severity or "-"
        typer.echo(f"[{entry.id}] sev={sev} loc={loc} :: {entry.raw}")
    for group in result.groups:
        key = ", ".join(f"{k}={v}" for k, v in group.key.items()) or "*"
        typer.echo(f"count={group.count} :: {key}")
    typer.echo(
        f"-- {len(result.rows)} rows, {len(result.groups)} groups, "
        f"{result.query_count} queries, rows_scanned={result.rows_scanned}"
    )


@logger_app.command("validate-plan")
def logger_validate_plan(
    file: Path = typer.Argument(..., exists=True, readable=True, dir_okay=False),
    as_json: bool = typer.Option(False, "--json", help="Emit errors as JSON"),
) -> None:
    """Validate a plan file against the frozen DSL. Exits 1 if invalid."""
    from common import SCHEMA_VERSION
    from logger import validate_plan

    validation = validate_plan(file.read_text(encoding="utf-8"))
    if validation.ok:
        if as_json:
            typer.echo(json.dumps({"ok": True, "errors": [], "schema_version": SCHEMA_VERSION}))
        else:
            typer.echo(f"ok — valid against schema {SCHEMA_VERSION}")
        return
    _echo_errors(validation, as_json=as_json)
    raise typer.Exit(code=1)


def _echo_errors(validation: object, *, as_json: bool) -> None:
    errors = getattr(validation, "errors", [])
    if as_json:
        typer.echo(
            json.dumps(
                {"ok": False, "errors": [e.model_dump(mode="json") for e in errors]}, indent=2
            )
        )
        return
    for err in errors:
        suffix = f" (got: {err.value})" if err.value is not None else ""
        typer.echo(f"{err.code.value}\t{err.path}\t{err.message}{suffix}", err=True)


if __name__ == "__main__":
    app()
