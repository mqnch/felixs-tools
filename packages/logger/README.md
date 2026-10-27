# Logger

Local log search and anomaly detection. Value is fewer round trips to a big model during debugging, plus catching novel patterns regex cannot express — not beating ripgrep at string search.

Canonical design context: [docs/sourceoftruth.md](../../docs/sourceoftruth.md) (§3.1, §7 step 2).

Mirror (read-only output, later): [mqnch/logger](https://github.com/mqnch/logger).

## Status

**Bare bones, usable — plus a frozen query DSL.** Parser → SQLite/FTS5 index → plan validator → plan executor → query planner → anomaly scorer. Uses the Router stub (stock/heuristic path). No fine-tuning.

As of [slice 002](../../docs/slices/002-extended-query-dsl.md) the query DSL is **frozen** at `common.SCHEMA_VERSION` = `1.0.0`. Changing it invalidates the training dataset and every checkpoint together ([decision 0002](../../docs/decisions/0002-post-train-the-query-planner.md)) — treat a change as a retrain, not an edit.

[Slice 003](../../docs/slices/003-loghub-corpus-ingest.md) adds `logger.corpora`: adapters for six LogHub datasets, seeded reproducible sampling, a corpus manifest with a content digest, and a licence gate. Corpus ingest is exposed as `felix logger ingest-corpus`.

## Components

| Piece | ML? | Role |
|---|---|---|
| Parser (`drain3`) | No | Cluster lines into templates |
| Index (SQLite + FTS5) | No | Structured fields + `LocationId` tags |
| Plan validator | No | Typed, structured rejection of malformed plans |
| Plan executor | No | Runs a plan as written; reports `rows_scanned` |
| Query planner | Yes (via Router) | NL question → a query plan |
| Anomaly scorer | Classical + optional Router | New/spiking templates |

Fine-tuning a small model is an optional side project, not required for Logger to work.

## Modules

| Module | Purpose |
|---|---|
| `parser` | drain3 templating |
| `index` | SQLite + FTS5 store, plan execution, `rows_scanned` |
| `validator` | `validate_plan()` → `PlanValidation` with typed `PlanErrorCode` errors |
| `timeutil` | Timestamp normalization and relative-offset (`-24h`) resolution |
| `planner` | NL question → `QueryPlan` via Router, with a deterministic fallback |
| `scorer` | Novel/spiking template detection |
| `service` | `Logger` façade wiring the above |
| `corpora` | LogHub dataset adapters, seeded sampling, corpus manifest + licence gate |

The plan schema itself lives in `common.query_plan` ([decision 0009](../../docs/decisions/0009-plan-schema-in-common.md)).

## Install

```bash
uv sync --package logger
```

## CLI

```bash
# ingest a log file
uv run felix logger ingest path/to/app.log --service api

# natural-language search
uv run felix logger search "find payment errors" --db .felix-tools/logger.db

# execute a query plan directly (--plan takes inline JSON or @file)
uv run felix logger query --plan '{"queries":[{"where":{"op":"and","of":[
  {"op":"severity","value":"ERROR"},
  {"op":"not","of":[{"op":"term","value":"healthcheck"}]},
  {"op":"time_range","since":"-24h"}]},"limit":20}]}'

# check a plan against the frozen schema; exits 1 with typed errors if invalid
uv run felix logger validate-plan plan.json --json
```

| Command | Exit codes |
|---|---|
| `felix logger query --plan <json\|@file> [--db] [--json]` | `0` ok, `2` invalid plan (errors on stderr) |
| `felix logger validate-plan <file> [--json]` | `0` valid, `1` invalid |

## Query DSL

A plan is a set of queries whose rows union. `where` is one recursive boolean
expression — `and` / `or` / `not` nest over `term`, `severity`, `template_id`,
`location_key`, and `time_range` leaves — so negation scopes inside a
disjunction. `aggregate` turns a query into `count` / `group_by` / `having` over
the same filter. Full shape and rationale: [slice 002](../../docs/slices/002-extended-query-dsl.md),
[decision 0008](../../docs/decisions/0008-recursive-boolean-filter-tree.md).

`rows_scanned` accompanies every result and reflects rows *examined*, not
returned ([decision 0011](../../docs/decisions/0011-rows-scanned-positive-skeleton.md)).
Relative bounds like `-24h` resolve against the corpus's newest timestamp, not
wall-clock ([decision 0010](../../docs/decisions/0010-corpus-relative-time-resolution.md)).

## Library

```python
from common import LocationId
from logger import Logger

log = Logger(".felix-tools/logger.db")
log.ingest_line(
    "ERROR payment failed order=42",
    location=LocationId(path="svc/api.log", service="api"),
    score=True,
)
hits = log.search("payment errors")
log.close()
```

Executing a plan directly, with validation first:

```python
from common import AndNode, NotNode, Query, QueryPlan, SeverityNode, TermNode
from logger import Logger, validate_plan

plan = QueryPlan(
    queries=[
        Query(
            label="unhealthy",
            where=AndNode(
                of=[
                    SeverityNode(value="ERROR"),
                    NotNode(of=[TermNode(value="healthcheck")]),
                ]
            ),
            limit=20,
        )
    ]
)

check = validate_plan(plan)
assert check.ok, check.errors  # PlanError(code=..., path=..., message=...)

log = Logger(".felix-tools/logger.db")
result = log.execute_plan(plan)
print(result.row_ids, result.rows_scanned)
log.close()
```

## Next

Use this on real daily log work and record friction in [docs/friction.md](../../docs/friction.md) before building Brain.
