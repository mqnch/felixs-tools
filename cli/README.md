# CLI

`felix` entrypoint that dispatches into package commands.

Canonical design context: [docs/sourceoftruth.md](../docs/sourceoftruth.md) (§4, §6).

## Status

Minimal Typer app. Logger subcommands are wired; Brain/Swarm land as those packages ship.

## Install / run

From the monorepo root:

```bash
uv sync --all-packages
uv run felix --help
uv run felix logger ingest path/to/app.log --service api
uv run felix logger search "find payment errors"
uv run felix logger query --plan '{"queries":[{"where":{"op":"severity","value":"ERROR"}}]}'
uv run felix logger validate-plan plan.json --json
```

## Commands

| Command | Purpose | Exit codes |
|---|---|---|
| `felix logger ingest <path>` | Index a log file | `0` |
| `felix logger search <question>` | Natural-language search via the planner | `0` |
| `felix logger query --plan <json\|@file>` | Execute a query plan against the index | `0` ok, `2` invalid plan |
| `felix logger validate-plan <file>` | Check a plan against the frozen DSL | `0` valid, `1` invalid |

Both plan commands accept `--json` for machine-readable output; invalid plans
print typed errors (code, path, message) rather than a bare failure.

## Layout

- `src/felixs_cli/main.py` — root app + package sub-apps

Keep package logic in `packages/*`; this package should stay a thin dispatcher.
