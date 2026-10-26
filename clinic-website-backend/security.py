"""Admin session tokens, password checks and a small in-memory rate limiter.

Standard library only. Tokens are ``base64url(payload).base64url(HMAC-SHA256)``
and expire. They are stateless, so a restart does not log anyone out unless
the admin password / SECRET_KEY changed.
"""
from __future__ import annotations

import base64
import hashlib
import hmac
import json
import threading
import time
from collections import deque


def _b64(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).rstrip(b"=").decode("ascii")


def _unb64(text: str) -> bytes:
    return base64.urlsafe_b64decode(text + "=" * (-len(text) % 4))


def sign_token(secret: str, ttl_seconds: int, now: float | None = None) -> str:
    now = time.time() if now is None else now
    payload = _b64(json.dumps({"exp": int(now + ttl_seconds), "v": 1}, separators=(",", ":")).encode())
    sig = _b64(hmac.new(secret.encode(), payload.encode(), hashlib.sha256).digest())
    return f"{payload}.{sig}"


def verify_token(secret: str, token: str | None, now: float | None = None) -> bool:
    if not token or token.count(".") != 1:
        return False
    payload, sig = token.split(".")
    expected = _b64(hmac.new(secret.encode(), payload.encode(), hashlib.sha256).digest())
    if not hmac.compare_digest(sig, expected):
        return False
    try:
        exp = json.loads(_unb64(payload))["exp"]
    except (ValueError, KeyError, TypeError):
        return False
    now = time.time() if now is None else now
    return isinstance(exp, int) and exp > now


def passwords_match(supplied: str, expected: str) -> bool:
    """Constant-time comparison (hashes first so length is not leaked)."""
    a = hashlib.sha256((supplied or "").encode()).digest()
    b = hashlib.sha256((expected or "").encode()).digest()
    return hmac.compare_digest(a, b) and bool(expected)


class RateLimiter:
    """Sliding-window counter keyed by an arbitrary string (e.g. client IP)."""

    def __init__(self, window_seconds: int) -> None:
        self.window = window_seconds
        self._hits: dict[str, deque[float]] = {}
        self._lock = threading.Lock()

    def _prune(self, key: str, now: float) -> deque[float]:
        q = self._hits.setdefault(key, deque())
        while q and q[0] <= now - self.window:
            q.popleft()
        return q

    def hit(self, key: str, now: float | None = None) -> int:
        """Record one event and return how many fall inside the window."""
        now = time.monotonic() if now is None else now
        with self._lock:
            q = self._prune(key, now)
            q.append(now)
            if len(self._hits) > 5000:  # keep memory bounded
                for k in [k for k, v in self._hits.items() if not v or v[-1] <= now - self.window]:
                    self._hits.pop(k, None)
            return len(q)

    def count(self, key: str, now: float | None = None) -> int:
        now = time.monotonic() if now is None else now
        with self._lock:
            return len(self._prune(key, now))

    def reset(self, key: str) -> None:
        with self._lock:
            self._hits.pop(key, None)
