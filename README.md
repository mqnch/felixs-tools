# Felix's Tools

Personal, modular CLI toolkit for fullstack, research, and ML work.

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
cli/        # `flx` entrypoint
```

## Setup

```bash
uv sync --all-packages
```

## Friction log

Bare-bones pain points go in [docs/friction.md](docs/friction.md) — see source of truth §2.2.
