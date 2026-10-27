# 0007 — Training code lives in `packages/planner-rl`, mirrored to a standalone public repo

**Date:** 2026-08-15
**Status:** Accepted
**Affects:** source of truth §4, §5
**Slice:** [002](../slices/002-extended-query-dsl.md) onward

## Context

The training work needs to be legible to a stranger evaluating it, which argues for a clean single-purpose public repo. It also depends intimately on the DSL, the index, and the query executor in `packages/logger`, which argues for living in the monorepo. §4 also states the monorepo is the only place development happens.

## Decision

A new workspace package `packages/planner-rl/`, depending on `logger` and `common`, mirrored to a standalone public repo via the existing §5 mirror workflow.

The mirror machinery designed in §5 already solves exactly this problem, so no new mechanism is needed — only adding `planner-rl` to the workflow's path filter and creating the target repo.

## Alternatives rejected

| Option | Why rejected |
|---|---|
| `packages/logger/training/` | Tightest coupling and least ceremony, but buried inside a personal monorepo — a reviewer has to understand the whole project before finding the work being showcased |
| Fully separate repo from day one | Would duplicate the DSL, index, and executor, all of which change during slice 002. The trained model's DSL would drift from the tool's actual DSL — the exact class of bug that silently invalidates every reported result |

## Consequences

- §4's tree and §5's mirrored-package list are edited; a new mirror repo must be created and added to `MIRROR_TOKEN`'s scope.
- The §5 force-push caveat now applies to a repo intended for public consumption: its README must state that consumers re-clone rather than `git pull`.
- `planner-rl` depends on `logger`, so the mirrored repo is not independently installable without `logger`. Acceptable — the artifact is the method, results, and reproducible eval, not a pip-installable library.

## Reversal trigger

If the mirror ever needs to accept issues or external PRs as a real public project, promote it per §5's PR-based path rather than continuing to force-push over contributor history.
