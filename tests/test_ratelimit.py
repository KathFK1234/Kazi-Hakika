from app.services.ratelimit import Limit, RateLimiter

LIMIT = Limit("test", 3, 60)


class Clock:
    def __init__(self) -> None:
        self.now = 1000.0

    def __call__(self) -> float:
        return self.now


def make(max_keys: int = 50_000) -> tuple[RateLimiter, Clock]:
    limiter = RateLimiter(max_keys=max_keys)
    clock = Clock()
    limiter._now = clock
    return limiter, clock


def test_counts_up_to_the_limit_then_refuses() -> None:
    limiter, _ = make()
    assert [limiter.hit(LIMIT, "k") for _ in range(4)] == [True, True, True, False]
    assert limiter.blocked(LIMIT, "k")
    assert not limiter.blocked(LIMIT, "other")


def test_window_resets() -> None:
    limiter, clock = make()
    for _ in range(3):
        limiter.hit(LIMIT, "k")
    assert limiter.retry_after(LIMIT, "k") == 61
    clock.now += 30
    assert limiter.retry_after(LIMIT, "k") == 31
    clock.now += 31
    assert not limiter.blocked(LIMIT, "k")
    assert limiter.hit(LIMIT, "k")


def test_blocked_does_not_count() -> None:
    limiter, _ = make()
    for _ in range(10):
        limiter.blocked(LIMIT, "k")
    assert limiter.hit(LIMIT, "k")


def test_memory_is_capped_and_live_counters_survive() -> None:
    limiter, clock = make(max_keys=10)
    limiter.hit(LIMIT, "old")
    clock.now += 4000  # "old" is now over an hour stale
    for i in range(9):
        limiter.hit(LIMIT, f"k{i}")
    for _ in range(3):
        limiter.hit(LIMIT, "busy")
    # Adding one more key evicts the stale entry first, not live ones.
    limiter.hit(LIMIT, "new")
    assert ("test", "old") not in limiter._hits
    assert limiter.blocked(LIMIT, "busy")
    for i in range(100):
        limiter.hit(LIMIT, f"flood{i}")
    assert len(limiter._hits) <= 10
