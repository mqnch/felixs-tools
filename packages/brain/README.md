# Brain

Persistent structural knowledge graph of a codebase, built from git history and static analysis — not by having an LLM read files.

Canonical design context: [docs/sourceoftruth.md](../../docs/sourceoftruth.md) (§3.2, §7 step 3).

Mirror (read-only output, later): [mqnch/brain](https://github.com/mqnch/brain).

## Status

**Not built yet.** Package scaffold only. Result shapes live in `felixs-common` (`BrainQueryResult`, etc.).

Build Brain only after Logger has been used for real work.

## Why in-house

Existing AST-graph tools don't model git co-change history or ownership. That layer is the differentiator. No model dependency — agents emit structured queries directly.

## Planned build order

1. Git co-change / ownership graph from `git log` (ship first)
2. Single-language tree-sitter extraction, full rebuild only
3. Naive name-based call linking (accept same-name collision risk)
4. Import-aware resolution (`tree-sitter-stack-graphs`) only if naive linking hurts in practice
5. More languages + incremental re-index — deferred

## Interfaces (when built)

- CLI and Python library from day one
- MCP server only on demonstrated need (external agent host)
- Nodes keyed by shared `LocationId` from `felixs-common` so Swarm can join Logger anomalies to blast radius

## Install

```bash
uv sync --package felixs-brain
```

## Deferred

Incremental updates, multi-language support, stack-graphs resolution — see source of truth §9.
