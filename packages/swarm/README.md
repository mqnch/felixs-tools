# Swarm

Orchestration engine. Runs **presets** — declarative pipeline configs, not new packages — as a sequence/DAG over Logger, Brain, LLM (via Router), and external systems.

Canonical design context: [docs/sourceoftruth.md](../../docs/sourceoftruth.md) (§3.4, §7 step 5).

Mirror (read-only output, later): [mqnch/swarm](https://github.com/mqnch/swarm).

## Status

**Not built yet.** Package scaffold only. A minimal preset schema placeholder lives in `common`; the real schema is intentionally undecided until manual Logger/Brain workflows reveal what presets need.

## Why last

Swarm orchestrates things that must already exist. Build it only after weeks of running Logger/Brain workflows by hand.

## Design constraints

- **Human-gated side effects** — opening a PR, posting to Slack, modifying tickets always requires approval (permanent)
- **Idempotent / retry-safe** side-effecting steps
- Calls Brain and Logger via **Python imports**, not MCP
- MCP **client** for third-party servers (GitHub, Jira) once Swarm exists
- MCP **server** (expose `run_preset(...)`) only on demonstrated need

## Planned presets (config in repo `presets/`, not new packages)

- Ticket → PR (governance check before real work data — §2.4)
- Code review
- Incident response
- Docs drift
- Flake triage
- Paper → code

## Install

```bash
uv sync --package swarm
```

## Litmus test

If an idea is only “an LLM prompt + tool loop,” it belongs here as a preset — not as a new package.