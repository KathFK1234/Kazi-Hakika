import threading
import time

from app.services import passwords


def test_hashing_is_capped_at_four_at_a_time(monkeypatch: object) -> None:
    active = 0
    peak = 0
    lock = threading.Lock()
    real = passwords._hasher

    class SlowHasher:
        def hash(self, password: str) -> str:
            return slow_hash(password)

    def slow_hash(password: str) -> str:
        nonlocal active, peak
        with lock:
            active += 1
            peak = max(peak, active)
        time.sleep(0.05)
        with lock:
            active -= 1
        return real.hash(password)

    monkeypatch.setattr(passwords, "_hasher", SlowHasher())  # type: ignore[attr-defined]
    threads = [
        threading.Thread(target=passwords.hash_password, args=(f"password {i}",)) for i in range(12)
    ]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    assert 1 < peak <= passwords.MAX_CONCURRENT_HASHES


def test_verify_round_trip_and_unknown_user() -> None:
    h = passwords.hash_password("correct horse battery")
    assert h.startswith("$argon2id$v=19$m=19456,t=2,p=1$")
    assert passwords.verify_password(h, "correct horse battery")
    assert not passwords.verify_password(h, "wrong")
    assert not passwords.verify_password(None, "anything")
    assert not passwords.verify_password("not-a-hash", "anything")
