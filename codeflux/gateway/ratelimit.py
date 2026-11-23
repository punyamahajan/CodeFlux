from __future__ import annotations

import collections
import math
import time


class SlidingWindowRpmLimiter:
    """In-memory sliding-window rate limiter per API key.

    Tracks timestamps of requests within a sliding 60-second window.
    Returns (allowed, retry_after_seconds).
    """

    def __init__(self, window_seconds: float = 60.0):
        self.window_seconds = window_seconds
        self._history: dict[str, collections.deque[float]] = collections.defaultdict(
            collections.deque
        )

    def check_and_record(self, key_id: str, rpm_limit: int) -> tuple[bool, int]:
        """Check if key has capacity in sliding window.

        If allowed, records the request and returns (True, 0).
        If limit exceeded, returns (False, retry_after_seconds) without recording.
        """
        now = time.monotonic()
        history = self._history[key_id]
        cutoff = now - self.window_seconds

        # Evict timestamps older than 60 seconds
        while history and history[0] <= cutoff:
            history.popleft()

        if len(history) >= rpm_limit:
            oldest = history[0]
            retry_after = max(1, math.ceil(self.window_seconds - (now - oldest)))
            return False, retry_after

        history.append(now)
        return True, 0

    def reset(self) -> None:
        """Clear all rate limit history."""
        self._history.clear()
