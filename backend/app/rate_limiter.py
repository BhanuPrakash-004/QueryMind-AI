"""Simple in-memory thread-safe rate limiter for API protection."""

from __future__ import annotations

import time
from collections import defaultdict
from threading import Lock

_MAX_REQUESTS_PER_MINUTE = 120
_lock = Lock()
_requests: dict[str, list[float]] = defaultdict(list)


def check_rate_limit(client_ip: str, max_requests: int | None = None) -> tuple[bool, int]:
    """Check if a client IP is within the allowed request rate.

    Returns:
        (is_allowed, remaining_requests)
    """
    limit = max_requests if max_requests is not None else _MAX_REQUESTS_PER_MINUTE
    now = time.monotonic()
    cutoff = now - 60.0

    with _lock:
        timestamps = _requests[client_ip]
        # Purge timestamps older than 60 seconds
        active_timestamps = [t for t in timestamps if t > cutoff]
        _requests[client_ip] = active_timestamps

        if len(active_timestamps) >= limit:
            return False, 0

        active_timestamps.append(now)
        remaining = limit - len(active_timestamps)
        return True, remaining


def reset_rate_limits() -> None:
    """Clear all rate limit buckets (useful for test isolation)."""
    with _lock:
        _requests.clear()
