from __future__ import annotations

import time

from codeflux.gateway.ratelimit import SlidingWindowRpmLimiter


def test_sliding_window_rpm_limiter_allows_under_limit():
    limiter = SlidingWindowRpmLimiter(window_seconds=60.0)

    # 3 requests allowed when limit is 3
    for _ in range(3):
        allowed, retry_after = limiter.check_and_record("key_1", rpm_limit=3)
        assert allowed is True
        assert retry_after == 0


def test_sliding_window_rpm_limiter_rejects_over_limit():
    limiter = SlidingWindowRpmLimiter(window_seconds=60.0)

    # Allow 2
    for _ in range(2):
        allowed, retry_after = limiter.check_and_record("key_2", rpm_limit=2)
        assert allowed is True

    # 3rd request rejected
    allowed, retry_after = limiter.check_and_record("key_2", rpm_limit=2)
    assert allowed is False
    assert 1 <= retry_after <= 60


def test_sliding_window_window_expiry():
    # Use very small window for test
    limiter = SlidingWindowRpmLimiter(window_seconds=0.05)

    allowed, _ = limiter.check_and_record("key_3", rpm_limit=1)
    assert allowed is True

    # Immediate next request rejected
    allowed2, _ = limiter.check_and_record("key_3", rpm_limit=1)
    assert allowed2 is False

    # Wait for window to pass
    time.sleep(0.06)

    # Now allowed again
    allowed3, _ = limiter.check_and_record("key_3", rpm_limit=1)
    assert allowed3 is True
