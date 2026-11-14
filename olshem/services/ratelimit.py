"""In-memory sliding-window rate limit per client IP and action.

Protects the paid AI quota from someone uploading in a loop. It lives in the process, so it
resets on restart and is not shared between instances (use Redis for a multi-instance setup)."""
from __future__ import annotations

import threading
import time
from collections import defaultdict, deque

from fastapi import HTTPException, Request

from ..config import settings

_hits: dict[tuple[str, str], deque[float]] = defaultdict(deque)
_lock = threading.Lock()
LABELS = {"submit": "жұмыс жіберу", "assign": "тапсырма құру", "ai_test": "ЖИ баптауларын тексеру"}


def client_ip(request: Request) -> str:
    hops = settings.trust_proxy_hops
    xff = request.headers.get("x-forwarded-for", "")
    if hops > 0 and xff:
        parts = [p.strip() for p in xff.split(",") if p.strip()]
        if parts:  # the entry appended by our outermost trusted proxy cannot be forged by the client
            return parts[-hops] if len(parts) >= hops else parts[0]
    return request.client.host if request.client else "unknown"


def hit(action: str, key: str, limit: int | None = None, window: int | None = None) -> None:
    limit = settings.rate_limits.get(action, 0) if limit is None else limit
    window = window or settings.rate_window_s
    if limit <= 0:
        return
    now = time.monotonic()
    with _lock:
        q = _hits[(action, key)]
        while q and now - q[0] >= window:
            q.popleft()
        if len(q) >= limit:
            wait = int(window - (now - q[0])) + 1
            raise HTTPException(429, f"Тым жиі: {LABELS.get(action, action)} шегі — {window // 60} минутта {limit} рет. "
                                     f"{max(1, wait // 60)} минуттан кейін қайталаңыз.",
                                headers={"Retry-After": str(wait)})
        q.append(now)


def limit(action: str):
    """FastAPI dependency: `_: None = Depends(ratelimit.limit("submit"))`."""
    def dep(request: Request) -> None:
        hit(action, client_ip(request))
    return dep


def reset() -> None:
    with _lock:
        _hits.clear()
