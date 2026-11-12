"""Password hashing, tokens, and the rate limiter."""

from __future__ import annotations

import time

import pytest

from app.security import (
    RateLimiter,
    create_token,
    decode_token,
    hash_password,
    verify_password,
)


class TestPasswords:
    def test_hash_is_not_the_password(self):
        h = hash_password("my-secret-password")
        assert h != "my-secret-password"
        assert h.startswith("$2b$")

    def test_verify_correct(self):
        h = hash_password("my-secret-password")
        assert verify_password("my-secret-password", h)

    def test_verify_wrong(self):
        h = hash_password("my-secret-password")
        assert not verify_password("my-secret-passwerd", h)

    def test_same_password_different_hashes(self):
        # bcrypt salts, so two hashes of the same input must differ.
        assert hash_password("same-password") != hash_password("same-password")

    def test_overlong_password_refused(self):
        with pytest.raises(ValueError):
            hash_password("x" * 100)

    def test_verify_overlong_returns_false(self):
        h = hash_password("normal-password")
        assert not verify_password("x" * 100, h)

    def test_verify_garbage_hash_returns_false(self):
        assert not verify_password("anything", "not-a-bcrypt-hash")


class TestTokens:
    def test_roundtrip(self):
        token = create_token("user-123")
        assert decode_token(token) == "user-123"

    def test_garbage_token(self):
        assert decode_token("not.a.token") is None

    def test_tampered_token(self):
        token = create_token("user-123")
        tampered = token[:-4] + "aaaa"
        assert decode_token(tampered) is None


class TestRateLimiter:
    def test_allows_under_limit(self):
        rl = RateLimiter(limit=3, window_seconds=60)
        for _ in range(3):
            allowed, _ = rl.check("1.2.3.4")
            assert allowed

    def test_blocks_over_limit(self):
        rl = RateLimiter(limit=2, window_seconds=60)
        rl.check("1.2.3.4")
        rl.check("1.2.3.4")
        allowed, retry = rl.check("1.2.3.4")
        assert not allowed
        assert retry >= 1

    def test_separate_keys_are_independent(self):
        rl = RateLimiter(limit=1, window_seconds=60)
        assert rl.check("a")[0]
        assert rl.check("b")[0]
        assert not rl.check("a")[0]

    def test_window_expiry(self):
        rl = RateLimiter(limit=1, window_seconds=1)
        assert rl.check("k")[0]
        assert not rl.check("k")[0]
        time.sleep(1.05)
        assert rl.check("k")[0]

    def test_reset_clears(self):
        rl = RateLimiter(limit=1, window_seconds=60)
        rl.check("k")
        assert not rl.check("k")[0]
        rl.reset()
        assert rl.check("k")[0]
