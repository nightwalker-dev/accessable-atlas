"""Sliding-window rate limiter and idempotency key store for retry-safe writes."""

from __future__ import annotations

import threading
import time
from collections import deque
from typing import Any


class RateLimitExceededError(Exception):
    """Raised when a client exceeds its allowed request budget within the sliding window."""

    def __init__(self, retry_after_seconds: int, limit: int) -> None:
        super().__init__(f"Rate limit of {limit}/min exceeded. Retry after {retry_after_seconds}s.")
        self.retry_after_seconds = max(1, retry_after_seconds)
        self.limit = limit


class SlidingWindowRateLimiter:
    """Thread-safe in-memory sliding-window rate limiter keyed by bucket and client identifier."""

    def __init__(self, window_seconds: int = 60) -> None:
        self.window_seconds = window_seconds
        self._buckets: dict[str, deque[float]] = {}
        self._lock = threading.Lock()

    def check_and_record(self, bucket_key: str, limit: int) -> dict[str, int]:
        """Record a request and raise RateLimitExceededError if limit is exceeded."""
        now = time.monotonic()
        cutoff = now - self.window_seconds
        with self._lock:
            history = self._buckets.get(bucket_key)
            if history is None:
                history = deque()
                self._buckets[bucket_key] = history
            while history and history[0] <= cutoff:
                history.popleft()
            if len(history) >= limit:
                oldest = history[0]
                retry_after = int(max(1.0, (oldest + self.window_seconds) - now))
                raise RateLimitExceededError(retry_after_seconds=retry_after, limit=limit)
            history.append(now)
            remaining = max(0, limit - len(history))
            return {
                "limit": limit,
                "remaining": remaining,
                "reset_seconds": self.window_seconds,
            }

    def reset(self) -> None:
        """Clear all rate-limit buckets (used in test isolation)."""
        with self._lock:
            self._buckets.clear()


class IdempotencyStore:
    """Bounded store for idempotent write responses keyed by (user_id, endpoint, idempotency_key)."""

    def __init__(self, ttl_seconds: int = 600, max_entries: int = 1000) -> None:
        self.ttl_seconds = ttl_seconds
        self.max_entries = max_entries
        self._entries: dict[str, tuple[float, int, dict[str, Any]]] = {}
        self._lock = threading.Lock()

    def get(self, composite_key: str) -> tuple[int, dict[str, Any]] | None:
        now = time.monotonic()
        with self._lock:
            entry = self._entries.get(composite_key)
            if not entry:
                return None
            expires_at, status_code, body = entry
            if now >= expires_at:
                del self._entries[composite_key]
                return None
            return status_code, body

    def put(self, composite_key: str, status_code: int, body: dict[str, Any]) -> None:
        now = time.monotonic()
        with self._lock:
            if len(self._entries) >= self.max_entries:
                # Evict expired or oldest entries
                expired = [k for k, (exp, _, _) in self._entries.items() if now >= exp]
                for k in expired:
                    del self._entries[k]
                if len(self._entries) >= self.max_entries:
                    oldest_key = next(iter(self._entries))
                    del self._entries[oldest_key]
            self._entries[composite_key] = (now + self.ttl_seconds, status_code, body)

