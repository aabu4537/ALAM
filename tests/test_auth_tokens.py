"""Signed session tokens (M7 session 2, ADR-0017). No I/O, no database."""

from __future__ import annotations

import datetime as dt

from alam.auth.tokens import issue_token, verify_token

_SECRET = b"a-test-secret"
_NOW = dt.datetime(2026, 8, 2, tzinfo=dt.UTC)
_TTL = dt.timedelta(days=30)


class TestIssueAndVerifyToken:
    def test_a_freshly_issued_token_is_valid(self) -> None:
        token = issue_token(secret=_SECRET, now=_NOW, ttl=_TTL)

        assert verify_token(token, secret=_SECRET, now=_NOW) is True

    def test_still_valid_just_before_expiry(self) -> None:
        token = issue_token(secret=_SECRET, now=_NOW, ttl=_TTL)
        just_before_expiry = _NOW + _TTL - dt.timedelta(seconds=1)

        assert verify_token(token, secret=_SECRET, now=just_before_expiry) is True

    def test_expired_at_the_exact_expiry_instant(self) -> None:
        token = issue_token(secret=_SECRET, now=_NOW, ttl=_TTL)

        assert verify_token(token, secret=_SECRET, now=_NOW + _TTL) is False

    def test_expired_well_past_ttl(self) -> None:
        token = issue_token(secret=_SECRET, now=_NOW, ttl=_TTL)
        long_after = _NOW + _TTL + dt.timedelta(days=365)

        assert verify_token(token, secret=_SECRET, now=long_after) is False

    def test_a_tampered_signature_is_rejected(self) -> None:
        token = issue_token(secret=_SECRET, now=_NOW, ttl=_TTL)
        payload, _, signature = token.partition(".")
        tampered = f"{payload}.{'0' * len(signature)}"

        assert verify_token(tampered, secret=_SECRET, now=_NOW) is False

    def test_a_tampered_payload_is_rejected(self) -> None:
        token = issue_token(secret=_SECRET, now=_NOW, ttl=_TTL)
        payload, _, signature = token.partition(".")
        forged_far_future_payload = str(int(payload) + 1_000_000)
        tampered = f"{forged_far_future_payload}.{signature}"

        assert verify_token(tampered, secret=_SECRET, now=_NOW) is False

    def test_the_wrong_secret_is_rejected(self) -> None:
        token = issue_token(secret=_SECRET, now=_NOW, ttl=_TTL)

        assert verify_token(token, secret=b"a-different-secret", now=_NOW) is False

    def test_an_empty_string_is_rejected(self) -> None:
        assert verify_token("", secret=_SECRET, now=_NOW) is False

    def test_garbage_input_is_rejected_not_an_exception(self) -> None:
        assert verify_token("not-a-real-token-at-all", secret=_SECRET, now=_NOW) is False

    def test_a_non_numeric_payload_is_rejected(self) -> None:
        assert verify_token("not-a-number.deadbeef", secret=_SECRET, now=_NOW) is False

    def test_extra_separators_are_rejected(self) -> None:
        token = issue_token(secret=_SECRET, now=_NOW, ttl=_TTL)

        assert verify_token(f"{token}.extra", secret=_SECRET, now=_NOW) is False

    def test_two_tokens_issued_for_the_same_instant_are_identical(self) -> None:
        """Deterministic given the same inputs — no randomness, so a test
        can assert exact equality rather than just "parses back OK"."""
        first = issue_token(secret=_SECRET, now=_NOW, ttl=_TTL)
        second = issue_token(secret=_SECRET, now=_NOW, ttl=_TTL)

        assert first == second
