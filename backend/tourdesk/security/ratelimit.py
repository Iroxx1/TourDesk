"""In-memory sliding-window rate limiter (per process, thread-safe).

Account lockouts are persisted in the database (``users.locked_until``); this limiter
protects login per IP and the API in general.
"""

from __future__ import annotations

import threading
import time
from collections import deque


class SlidingWindowLimiter:
    def __init__(self, limit: int, window_seconds: float) -> None:
        self.limit = limit
        self.window = window_seconds
        self._hits: dict[str, deque[float]] = {}
        self._lock = threading.Lock()
        self._last_cleanup = time.monotonic()

    def _prune(self, q: deque[float], now: float) -> None:
        border = now - self.window
        while q and q[0] <= border:
            q.popleft()

    def hit(self, key: str) -> bool:
        """Register a hit. Returns ``False`` if the limit is exceeded."""
        now = time.monotonic()
        with self._lock:
            q = self._hits.setdefault(key, deque())
            self._prune(q, now)
            if len(q) >= self.limit:
                return False
            q.append(now)
            if now - self._last_cleanup > 300:
                self._cleanup(now)
            return True

    def would_block(self, key: str) -> bool:
        now = time.monotonic()
        with self._lock:
            q = self._hits.get(key)
            if not q:
                return False
            self._prune(q, now)
            return len(q) >= self.limit

    def retry_after(self, key: str) -> int:
        now = time.monotonic()
        with self._lock:
            q = self._hits.get(key)
            if not q:
                return 0
            return max(1, int(q[0] + self.window - now) + 1)

    def reset(self, key: str) -> None:
        with self._lock:
            self._hits.pop(key, None)

    def clear(self) -> None:
        with self._lock:
            self._hits.clear()

    def _cleanup(self, now: float) -> None:
        for key in list(self._hits):
            q = self._hits[key]
            self._prune(q, now)
            if not q:
                del self._hits[key]
        self._last_cleanup = now


_limiters: dict[str, SlidingWindowLimiter] = {}
_limiters_lock = threading.Lock()


def get_limiter(name: str, limit: int, window_seconds: float) -> SlidingWindowLimiter:
    with _limiters_lock:
        limiter = _limiters.get(name)
        if limiter is None or limiter.limit != limit or limiter.window != window_seconds:
            limiter = SlidingWindowLimiter(limit, window_seconds)
            _limiters[name] = limiter
        return limiter


def reset_all_limiters() -> None:
    with _limiters_lock:
        for limiter in _limiters.values():
            limiter.clear()
