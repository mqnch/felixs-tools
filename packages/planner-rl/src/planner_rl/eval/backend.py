"""One client for every evaluated model: OpenAI-compatible chat completions.

Stock Qwen3.5 runs locally behind `mlx_lm.server` (or vLLM on the cluster) and
frontier models run through OpenRouter. All of them speak the same API, so the
harness has one code path and the only per-model difference is `base_url`.
"""

from __future__ import annotations

import os
import time
from dataclasses import dataclass

from planner_rl.http import NETWORK_ERROR, post_json

OPENROUTER_BASE_URL = "https://openrouter.ai/api/v1"
LOCAL_BASE_URL = "http://127.0.0.1:8080/v1"
FATAL_STATUSES = frozenset({401, 402, 403})


@dataclass(frozen=True)
class Completion:
    text: str
    prompt_tokens: int | None
    completion_tokens: int | None
    latency_s: float
    cost_usd: float | None = None
    error: str | None = None


class ChatBackend:
    def __init__(
        self,
        model: str,
        *,
        base_url: str = OPENROUTER_BASE_URL,
        api_key: str | None = None,
        max_tokens: int = 1024,
        thinking: bool = False,
        effort: str | None = None,
        deadline_s: float = 300,
        max_retries: int = 6,
        post=post_json,
        sleep=time.sleep,
    ) -> None:
        if model.startswith("~"):
            raise ValueError(f"{model!r} is a floating alias; pin an exact slug")
        self.model = model
        self.base_url = base_url.rstrip("/")
        # Some models (Sonnet 5.5) cannot turn reasoning off; an effort level
        # implies thinking so the results file never claims it was off.
        self.thinking = thinking or effort is not None
        self.effort = effort
        self._openrouter = "openrouter.ai" in self.base_url
        key = api_key or (os.environ.get("OPENROUTER_API_KEY") if self._openrouter else None)
        if self._openrouter and not key:
            raise RuntimeError("OPENROUTER_API_KEY is not set")
        self._headers = {"Content-Type": "application/json"}
        if key:
            self._headers["Authorization"] = f"Bearer {key}"
        self._max_tokens = max_tokens
        self._deadline_s = deadline_s
        self._max_retries = max_retries
        self._post = post
        self._sleep = sleep

    def complete(self, system: str, user: str, *, shared_prefix: str = "") -> Completion:
        """``shared_prefix + user`` is the user message; the prefix is the cacheable part."""
        user_content: object = shared_prefix + user
        if self.model.startswith("anthropic/") and shared_prefix:
            # Anthropic caches only up to an explicit breakpoint, and only past
            # 1024 tokens; the system prompt alone is shorter, so the breakpoint
            # goes after the corpus card. Same text, split into two blocks.
            user_content = [
                {"type": "text", "text": shared_prefix, "cache_control": {"type": "ephemeral"}},
                {"type": "text", "text": user},
            ]
        body: dict = {
            "model": self.model,
            "max_tokens": self._max_tokens,
            "temperature": 0,
            "messages": [
                {"role": "system", "content": system},
                {"role": "user", "content": user_content},
            ],
        }
        if self._openrouter:
            body["reasoning"] = {"effort": self.effort} if self.effort else {"enabled": self.thinking}
            body["usage"] = {"include": True}
        else:
            # Qwen3.5 chat templates think by default.
            body["chat_template_kwargs"] = {"enable_thinking": self.thinking}

        for attempt in range(self._max_retries + 1):
            # Latency is the successful attempt only; backoff is not the model's.
            started = time.monotonic()
            status, payload = self._post(
                f"{self.base_url}/chat/completions", self._headers, body, deadline_s=self._deadline_s
            )
            if status in (NETWORK_ERROR, 429) or status >= 500:
                if attempt == self._max_retries:
                    raise RuntimeError(f"model call failed after retries: HTTP {status} {payload}")
                self._sleep(2**attempt)
                continue
            break
        latency = time.monotonic() - started
        if status in FATAL_STATUSES:
            raise RuntimeError(f"provider rejected the request (HTTP {status}): {payload}")
        if status != 200:
            detail = str((payload.get("error") or {}).get("message", ""))[:200]
            return Completion("", None, None, latency, error=f"http_{status}: {detail}".rstrip(": "))
        message = ((payload.get("choices") or [{}])[0]).get("message") or {}
        usage = payload.get("usage") or {}
        return Completion(
            text=message.get("content") or "",
            prompt_tokens=usage.get("prompt_tokens"),
            completion_tokens=usage.get("completion_tokens"),
            latency_s=latency,
            cost_usd=usage.get("cost"),
        )
