"""Pass-through Router stub used until LiteLLM policy/cache lands."""

from __future__ import annotations

import json
import os
import re
import urllib.error
import urllib.request
from typing import Any

from common import RouterRequest, RouterResponse, TaskType


def complete(request: RouterRequest) -> RouterResponse:
    """Route a completion with no caching and no cascading.

    Tries a local Ollama HTTP endpoint when configured; otherwise returns a
    deterministic heuristic response so callers remain usable offline.
    """
    model = request.model or os.environ.get("FELIX_TOOLS_ROUTER_MODEL", "llama3.2")
    base = os.environ.get("OLLAMA_HOST", "http://127.0.0.1:11434").rstrip("/")

    try:
        content = _ollama_chat(base, model, request.messages, request.temperature)
        return RouterResponse(content=content, model=model, cached=False)
    except (urllib.error.URLError, TimeoutError, OSError, json.JSONDecodeError):
        content = _heuristic(request)
        return RouterResponse(
            content=content,
            model="stub-heuristic",
            cached=False,
            raw={"fallback": True, "task_type": request.task_type.value},
        )


def _ollama_chat(
    base: str,
    model: str,
    messages: list[dict[str, Any]],
    temperature: float | None,
) -> str:
    payload: dict[str, Any] = {
        "model": model,
        "messages": messages,
        "stream": False,
    }
    if temperature is not None:
        payload["options"] = {"temperature": temperature}
    data = json.dumps(payload).encode("utf-8")
    req = urllib.request.Request(
        f"{base}/api/chat",
        data=data,
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    with urllib.request.urlopen(req, timeout=30) as resp:
        body = json.loads(resp.read().decode("utf-8"))
    message = body.get("message") or {}
    content = message.get("content")
    if not isinstance(content, str):
        raise json.JSONDecodeError("missing message.content", "", 0)
    return content


def _heuristic(request: RouterRequest) -> str:
    text = _last_user_text(request.messages)
    if request.task_type == TaskType.LOG_QUERY_PLANNING:
        terms = _keywords(text)
        plan = {
            "queries": [
                {
                    "filters": {"severity": "error"} if "error" in text.lower() else {},
                    "terms": terms,
                    "limit": 50,
                }
            ]
        }
        return json.dumps(plan)
    if request.task_type == TaskType.ANOMALY_SCORING:
        return json.dumps({"novel": False, "score": 0.0, "reason": "stub"})
    return text


def _last_user_text(messages: list[dict[str, Any]]) -> str:
    for msg in reversed(messages):
        if msg.get("role") == "user":
            content = msg.get("content", "")
            return content if isinstance(content, str) else str(content)
    return ""


def _keywords(text: str) -> list[str]:
    tokens = re.findall(r"[A-Za-z_][A-Za-z0-9_]{2,}", text.lower())
    stop = {
        "the",
        "and",
        "for",
        "with",
        "from",
        "that",
        "this",
        "find",
        "show",
        "logs",
        "log",
        "error",
        "errors",
        "about",
        "what",
        "when",
        "where",
    }
    out: list[str] = []
    for tok in tokens:
        if tok in stop or tok in out:
            continue
        out.append(tok)
        if len(out) >= 8:
            break
    return out
