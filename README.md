# Felix's Tools

Personal, modular CLI toolkit for all dev work.

The canonical project brief — design philosophy, package boundaries, build order, and non-goals — lives in [docs/sourceoftruth.md](docs/sourceoftruth.md). Read that before adding packages or presets.

## Layout

```
packages/
  common/   # shared types and schemas (build first)
  router/   # litellm decision-policy + cache wrapper
  logger/   # log parse/index/query/anomaly
  brain/    # git co-change + structural graph
  swarm/    # preset DAG executor
presets/    # declarative Swarm pipelines
cli/        # `felix` entrypoint
```

Each package has its own README:

- [Common](packages/common/README.md)
- [Router](packages/router/README.md)
- [Logger](packages/logger/README.md)
- [Brain](packages/brain/README.md)
- [Swarm](packages/swarm/README.md)
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

## Friction log

Bare-bones pain points go in [docs/friction.md](docs/friction.md) — see source of truth §2.2.
