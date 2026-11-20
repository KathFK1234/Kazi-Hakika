"""Fixed-window, in-memory rate limits.

There is one web process (one Railway service), so memory is shared by every
request. Counters reset on restart, which only ever makes limits looser for a
moment. The table is capped so a flood of distinct keys can't grow memory.
"""

import threading
import time
from dataclasses import dataclass


@dataclass(frozen=True)
class Limit:
    name: str
    count: int
    seconds: int


class RateLimiter:
    def __init__(self, max_keys: int = 50_000) -> None:
        self._hits: dict[tuple[str, str], tuple[float, int]] = {}
        self._lock = threading.Lock()
        self._max_keys = max_keys
        self._now = time.monotonic

    def hit(self, limit: Limit, key: str) -> bool:
        """Count one attempt; False if the caller is over the limit."""
        now = self._now()
        bucket = (limit.name, key)
        with self._lock:
            start, count = self._hits.get(bucket, (now, 0))
            if now - start >= limit.seconds:
                start, count = now, 0
            if count >= limit.count:
                return False
            if bucket not in self._hits and len(self._hits) >= self._max_keys:
                self._evict(now)
            self._hits[bucket] = (start, count + 1)
            return True

    def blocked(self, limit: Limit, key: str) -> bool:
        """True if the key is at its limit, without counting an attempt."""
        now = self._now()
        with self._lock:
            start, count = self._hits.get((limit.name, key), (now, 0))
        return now - start < limit.seconds and count >= limit.count

    def retry_after(self, limit: Limit, key: str) -> int:
        with self._lock:
            start, _ = self._hits.get((limit.name, key), (self._now(), 0))
        return max(int(limit.seconds - (self._now() - start)) + 1, 1)

    def reset(self) -> None:
        with self._lock:
            self._hits.clear()

    def _evict(self, now: float) -> None:
        # Drop windows older than an hour; if still full, drop the oldest half.
        stale = [k for k, (start, _) in self._hits.items() if now - start > 3600]
        for k in stale:
            del self._hits[k]
        if len(self._hits) >= self._max_keys:
            for k in sorted(self._hits, key=lambda k: self._hits[k][0])[: self._max_keys // 2]:
                del self._hits[k]


# Failed logins per IP (successful ones never count).
LOGIN_PER_IP = Limit("login-ip", 5, 60)
# Failed logins only, so typing someone's email can't lock them out quickly:
# 10 an hour from one IP for one account, 50 an hour for one account overall.
LOGIN_FAILS_PER_EMAIL_IP = Limit("login-fail-email-ip", 10, 3600)
LOGIN_FAILS_PER_EMAIL = Limit("login-fail-email", 50, 3600)
SIGNUP_PER_IP = Limit("signup-ip", 5, 3600)
# One sign-up email (verification or already-registered) per address per day.
SIGNUP_EMAIL_PER_ADDRESS = Limit("signup-email", 1, 86400)
RESET_PER_IP = Limit("reset-ip", 5, 3600)
RESET_PER_EMAIL = Limit("reset-email", 3, 3600)
VERIFY_RESEND_PER_USER = Limit("verify-resend", 3, 86400)
TOKEN_USE_PER_IP = Limit("token-use-ip", 20, 3600)
