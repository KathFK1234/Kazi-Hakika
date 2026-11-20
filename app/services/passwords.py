"""argon2id with OWASP's minimum profile (19 MiB, t=2, p=1).

Kept deliberately small: the web service runs in 512 MB, and a burst of
logins at argon2-cffi's default 64 MiB each could exhaust it.
"""

import threading
from collections.abc import Callable

from argon2 import PasswordHasher
from argon2.exceptions import InvalidHashError, VerificationError, VerifyMismatchError

_hasher = PasswordHasher(time_cost=2, memory_cost=19 * 1024, parallelism=1)

# At most this many hashes in memory at once (4 x 19 MiB). Without a cap the
# request thread pool (40 threads) could run ~760 MiB of hashing at once.
MAX_CONCURRENT_HASHES = 4
_slots = threading.BoundedSemaphore(MAX_CONCURRENT_HASHES)


def _bounded[T](work: Callable[[], T]) -> T:
    with _slots:
        return work()


# Verified against when the email is unknown, so both paths take the same time.
_DUMMY_HASH = _hasher.hash("timing-equaliser-not-a-password")


def hash_password(password: str) -> str:
    return _bounded(lambda: _hasher.hash(password))


def verify_password(password_hash: str | None, password: str) -> bool:
    def check() -> bool:
        return _hasher.verify(password_hash or _DUMMY_HASH, password)

    try:
        return _bounded(check) and bool(password_hash)
    except (VerifyMismatchError, VerificationError, InvalidHashError):
        return False


def needs_rehash(password_hash: str) -> bool:
    return _hasher.check_needs_rehash(password_hash)
