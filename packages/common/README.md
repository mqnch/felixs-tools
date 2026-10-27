# Common

Shared types and schemas. Every other package builds against this contract.

Canonical design context: [docs/sourceoftruth.md](../../docs/sourceoftruth.md) (§4, §7 step 1).

## Status

**Implemented.** Types only — no parsing, git walking, or model calls.

## What it owns

| Module | Purpose |
|---|---|
| `location` | `LocationId` — file path + optional service label; join key for Logger ↔ Brain |
| `tasks` | `TaskType` taxonomy for Router decision policy |
| `router` | `RouterRequest` / `RouterResponse` shapes |
| `brain` | Coarse `BrainQueryResult` / node / edge shapes (exact query language still open) |
| `preset` | Minimal `Preset` / `PresetStep` placeholder (full schema deferred until real workflows) |
| `query_plan` | **Frozen** Logger query DSL — `SCHEMA_VERSION`, `QueryPlan` / `Query` / filter nodes / `Aggregate`, and the `PlanErrorCode` / `PlanError` / `PlanValidation` shapes |

## Install

From the monorepo root:

```bash
uv sync --package common
```

## Usage

```python
from common import LocationId, TaskType, RouterRequest

loc = LocationId(path="src/app.py", service="api")
assert loc.key() == "api:src/app.py"

req = RouterRequest(
    task_type=TaskType.LOG_QUERY_PLANNING,
    messages=[{"role": "user", "content": "find timeouts"}],
)
```

## Rules

- Add shared contracts here before duplicating shapes in other packages.
- Do not put business logic in this package. Declarative field constraints are fine; rules with judgment in them belong to the owning package ([decision 0009](../../docs/decisions/0009-plan-schema-in-common.md)).
- Prefer extending existing models over inventing parallel ones.
- **`query_plan` is a frozen training contract.** `SCHEMA_VERSION` is bumped, never silently edited — a change invalidates Logger's dataset and every trained checkpoint together ([decision 0002](../../docs/decisions/0002-post-train-the-query-planner.md)).
