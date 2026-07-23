# CLI

`flx` entrypoint that dispatches into package commands.

Canonical design context: [docs/sourceoftruth.md](../docs/sourceoftruth.md) (§4, §6).

## Status

Minimal Typer app. Logger subcommands are wired; Brain/Swarm land as those packages ship.

## Install / run

From the monorepo root:

```bash
uv sync --all-packages
uv run flx --help
uv run flx logger ingest path/to/app.log --service api
uv run flx logger search "find payment errors"
```

## Layout

- `src/felixs_cli/main.py` — root app + package sub-apps

Keep package logic in `packages/*`; this package should stay a thin dispatcher.
