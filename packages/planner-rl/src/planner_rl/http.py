"""Stdlib JSON POST shared by question authoring (slice 004) and eval (slice 005).

No SDK: one POST does not justify a dependency (decision 0016).
"""

from __future__ import annotations

import json
import time
import urllib.error
import urllib.request

# Pseudo-status for a request that never got an HTTP response.
NETWORK_ERROR = 0
REQUEST_DEADLINE_S = 90


def read_with_deadline(resp, deadline: float) -> bytes:
    """Read the whole body, giving up at ``deadline`` (a ``time.monotonic()`` value).

    OpenRouter writes keep-alive whitespace while an upstream provider works, so
    the socket timeout never fires on a request whose provider has hung: each
    keep-alive byte resets it. Only a deadline over the whole read catches that.
    """
    chunks = []
    while True:
        if time.monotonic() > deadline:
            raise TimeoutError(f"no complete response within {REQUEST_DEADLINE_S}s")
        chunk = resp.read1(65536)
        if not chunk:
            return b"".join(chunks)
        chunks.append(chunk)


def post_json(
    url: str, headers: dict[str, str], body: dict, *, deadline_s: float = REQUEST_DEADLINE_S
) -> tuple[int, dict]:
    req = urllib.request.Request(url, data=json.dumps(body).encode(), headers=headers, method="POST")
    deadline = time.monotonic() + deadline_s
    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            return resp.status, json.loads(read_with_deadline(resp, deadline))
    except urllib.error.HTTPError as exc:
        try:
            payload = json.loads(exc.read())
        except ValueError:
            payload = {}
        return exc.code, payload
    except (urllib.error.URLError, TimeoutError, ConnectionError, ValueError) as exc:
        # No usable HTTP response: a timeout, a dropped connection or a body that
        # is not JSON. Retryable, like a 5xx; uncaught, one of these killed all
        # three 20k runs at once.
        return NETWORK_ERROR, {"error": repr(exc)}
