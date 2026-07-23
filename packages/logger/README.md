# Logger

Local log search and anomaly detection. Value is fewer round trips to a big model during debugging, plus catching novel patterns regex cannot express — not beating ripgrep at string search.

Canonical design context: [docs/sourceoftruth.md](../../docs/sourceoftruth.md) (§3.1, §7 step 2).

Mirror (read-only output, later): [mqnch/logger](https://github.com/mqnch/logger).

## Status

**Bare bones, usable.** Parser → SQLite/FTS5 index → query planner → anomaly scorer. Uses the Router stub (stock/heuristic path). No fine-tuning.

## Components

| Piece | ML? | Role |
|---|---|---|
| Parser (`drain3`) | No | Cluster lines into templates |
| Index (SQLite + FTS5) | No | Structured fields + `LocationId` tags |
| Query planner | Yes (via Router) | NL question → structured queries |
| Anomaly scorer | Classical + optional Router | New/spiking templates |

Fine-tuning a small model is an optional side project, not required for Logger to work.

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
```

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

## Next

Use this on real daily log work and record friction in [docs/friction.md](../../docs/friction.md) before building Brain.
