# Router

Thin routing layer under model calls. Callers tag a `TaskType`; Router picks how the completion is served.

Canonical design context: [docs/sourceoftruth.md](../../docs/sourceoftruth.md) (§3.3, §7 step 4).

Monorepo-only — no standalone mirror. Thin internal wrapper over LiteLLM; not useful as its own repo.

## Status

**Stub.** Pass-through completion with no cache and no cascading. Tries local Ollama (`OLLAMA_HOST`, default `http://127.0.0.1:11434`); falls back to a deterministic heuristic so Logger stays usable offline.

Not yet the planned LiteLLM + decision-policy + exact-match cache wrapper. That lands after Logger (and later Brain) have generated real call patterns.

## Interface

Plain Python library — **not** an MCP server. Brain never depends on it.

```python
from felixs_common import RouterRequest, TaskType
from felixs_router import complete

response = complete(
    RouterRequest(
        task_type=TaskType.LOG_QUERY_PLANNING,
        messages=[{"role": "user", "content": "find payment errors"}],
    )
)
print(response.content, response.model, response.cached)
```

## Planned components (not built yet)

1. Rule-based decision policy by `TaskType`
2. Exact-match cache (`diskcache`) over normalized input hashes
3. Backend abstraction / retry via `litellm.completion` (SDK mode only — no proxy server)

Deferred: confidence cascading, semantic caching.

## Install

```bash
uv sync --package felixs-router
```

## Env

| Variable | Meaning |
|---|---|
| `OLLAMA_HOST` | Ollama base URL (stub) |
| `FELIXS_ROUTER_MODEL` | Default model name for Ollama (stub) |
