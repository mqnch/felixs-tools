# Felix's Tools

Personal, modular CLI toolkit for all dev work.

The canonical project brief — design philosophy, package boundaries, build order, and non-goals — lives in [docs/sourceoftruth.md](docs/sourceoftruth.md). Read that before adding packages or presets.

## Docs

| Doc | What it holds |
|---|---|
| [Source of truth](docs/sourceoftruth.md) | Canonical and current: what this is, why, what's deliberately not built |
| [Slices](docs/slices/README.md) | Append-only log of what shipped, and what each slice deliberately left out |
| [Decisions](docs/decisions/README.md) | Choices made after the brief, with the rejected alternatives and reversal triggers |
| [Friction](docs/friction.md) | Dated notes when a bare-bones piece cost real time — the evidence that justifies generalizing |
| [CLAUDE.md](CLAUDE.md) | Working rules and the documentation definition-of-done for anyone (human or AI) making changes |

## Layout

```
packages/
  common/   # shared types and schemas (build first)
  router/   # litellm decision-policy + cache wrapper
  logger/   # log parse/index/query/anomaly
  brain/    # git co-change + structural graph
  swarm/    # preset DAG executor
  planner-rl/ # post-training the query planner (current focus)
presets/    # declarative Swarm pipelines
cli/        # `felix` entrypoint
```

**Current focus:** post-training Logger's query planner with verifiable execution rewards — see [slices 002–012](docs/slices/README.md) and [decision 0001](docs/decisions/0001-post-trained-planner-is-primary-deliverable.md). Brain and Swarm are deferred behind it.

Each package has its own README:

- [Common](packages/common/README.md)
- [Router](packages/router/README.md)
- [Logger](packages/logger/README.md)
- [Brain](packages/brain/README.md)
- [Swarm](packages/swarm/README.md)
- [planner-rl](packages/planner-rl/README.md)
- [CLI](cli/README.md)

## Repos

- [mqnch/felixs-tools](https://github.com/mqnch/felixs-tools) — this monorepo (only place development happens)

Standalone package mirrors (read-only outputs; CI mirror not yet wired):

- [mqnch/swarm](https://github.com/mqnch/swarm)
- [mqnch/logger](https://github.com/mqnch/logger)
- [mqnch/brain](https://github.com/mqnch/brain)

Router and Common stay monorepo-only (internal libraries, not mirrored).

## Setup

```bash
uv sync --all-packages
```

## Making changes

Documentation ships with the change, not after it — see [CLAUDE.md](CLAUDE.md) for the definition of done. In short: a slice entry for anything that ships behavior, a decision record when a real alternative was rejected, a dated line in [docs/friction.md](docs/friction.md) whenever a bare-bones piece actually hurt (source of truth §2.2).
