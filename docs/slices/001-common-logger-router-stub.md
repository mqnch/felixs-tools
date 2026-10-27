# 001 — Common types, Logger bare bones, Router stub, `felix` CLI

**Date:** 2026-07-23
**Status:** Shipped
**Touches:** `packages/common`, `packages/logger`, `packages/router`, `cli`
**Source of truth:** §3.1, §3.3, §7 steps 1–2

> Backfilled on 2026-08-15 from git history and the code as it stands, at the point the slice log was introduced. Later slices are written as the work happens.

## What a person can now do

Ingest a log file and ask it a natural-language question from the CLI, with no cloud model and no fine-tuning.

```bash
uv sync --all-packages
uv run felix logger ingest path/to/app.log --service api
uv run felix logger search "find payment errors"
```

## How it works

- `common` holds the shared contract every other package builds against: `LocationId` (the Logger↔Brain join key), `TaskType`, `RouterRequest`/`RouterResponse`, coarse `BrainQueryResult` shapes, and a placeholder `Preset`. Types only — no logic.
- `logger` is the four-part pipeline from §3.1: `parser` (drain3 templating) → `index` (SQLite + FTS5, tagged with `LocationId`) → `planner` (NL → structured queries, via Router) → `scorer` (classical frequency/novelty first, Router only for optional judgment). `service.Logger` is the façade that wires them.
- `router` is a pass-through stub: tries local Ollama (`OLLAMA_HOST`), falls back to a deterministic heuristic so Logger stays usable offline. No LiteLLM, no cache, no policy.
- `cli` is a thin Typer dispatcher. Logger subcommands only; Brain/Swarm land with those packages.

## Deliberately not in this slice

- **Router as specified (§3.3)** — no LiteLLM, no `TaskType` decision policy, no exact-match cache. Per §7 step 4, Router is written for real only once Logger and Brain have produced real call patterns to route between. A stub now is the point, not a gap.
- **Fine-tuned small model for Logger** — §3.1 makes this an explicitly decoupled side project. Stock model + prompting is the supported path.
- **Brain and Swarm** — scaffold only. §7 orders them behind real daily use of Logger.
- **MCP servers** — none, for any package. §2.5: on demonstrated need, not as scaffolding.
- **Mirror workflow** — `.github/workflows/mirror.yml` is not written; `.github/workflows/` holds a `.gitkeep`. Mirror repos exist but are not yet fed.
- **Anomaly scorer as a continuous process** — scoring is opt-in per ingest (`score=True`), not a running service.

## Decisions made here

None recorded separately — every choice in this slice was already fixed by the source of truth (§3.1, §3.3, §7). This directory starts empty by design; §7 step 4 (Router made real) and Brain's linking strategy are the first places new decisions are expected.

## Friction observed

None recorded. Logger has not been used for real daily log work yet — which is exactly the gate on starting Brain.

## What this unlocks

- **Use Logger on real log-debugging work**, and write friction to [../friction.md](../friction.md). §2.2 makes this the evidence that decides what gets generalized.
- Only after that: Brain, in its own order (§3.2) — git co-change/ownership graph first, which also acts as a check on whether `common`'s types were right.
- Before pointing anything at real work tickets or source: the §2.4 governance check on sending code/ticket content to external APIs.
