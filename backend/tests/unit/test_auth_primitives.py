"""Password hashing, session tokens and the sign-in rate limiter."""

from __future__ import annotations

from app.auth.passwords import hash_password, needs_rehash, verify_password
from app.auth.rate_limit import LoginRateLimiter
from app.auth.tokens import new_session_token, token_digest

# A low iteration count keeps these tests fast; the format is what is under test.
FAST = 1_000


def test_a_hash_verifies_its_own_password_and_nothing_else() -> None:
    encoded = hash_password("correct horse battery", iterations=FAST)

    assert encoded.startswith("pbkdf2_sha256$1000$")
    assert verify_password("correct horse battery", encoded)
    assert not verify_password("correct horse batterY", encoded)


def test_hashes_are_salted() -> None:
    assert hash_password("same password here", iterations=FAST) != hash_password(
        "same password here", iterations=FAST
    )


def test_a_malformed_hash_never_verifies() -> None:
    assert not verify_password("anything", "not-a-hash")
    assert not verify_password("anything", "md5$1$x$y")
    assert not verify_password("anything", "pbkdf2_sha256$abc$x$y")


def test_weaker_parameters_are_flagged_for_rehash() -> None:
    assert needs_rehash(hash_password("a long enough password", iterations=FAST))
    assert needs_rehash("garbage")


def test_tokens_are_long_random_and_stored_only_as_a_digest() -> None:
    token = new_session_token()

    assert len(token) >= 43
    assert new_session_token() != token
    assert token_digest(token) == token_digest(token)
    assert len(token_digest(token)) == 64
    assert token not in token_digest(token)


class FakeClock:
    def __init__(self) -> None:
        self.now = 1_000.0

    def __call__(self) -> float:
        return self.now

    def advance(self, seconds: float) -> None:
        self.now += seconds


def test_a_key_is_locked_after_the_allowed_failures_until_the_window_passes() -> None:
    clock = FakeClock()
    limiter = LoginRateLimiter(max_failures=3, window_seconds=60, clock=clock)

    for _ in range(3):
        assert limiter.check("10.0.0.5|ops@venue.org") is None
        limiter.record_failure("10.0.0.5|ops@venue.org")

    wait = limiter.check("10.0.0.5|ops@venue.org")
    assert wait is not None and 0 < wait <= 60

    clock.advance(61)
    assert limiter.check("10.0.0.5|ops@venue.org") is None


def test_other_keys_are_unaffected_and_reset_clears_a_key() -> None:
    limiter = LoginRateLimiter(max_failures=1, window_seconds=60, clock=FakeClock())
    limiter.record_failure("a")

    assert limiter.check("a") is not None
    assert limiter.check("b") is None

    limiter.reset("a")
    assert limiter.check("a") is None
