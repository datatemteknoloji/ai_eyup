"""
Tests for auth endpoints: login, logout, JWT revocation.
"""
import pytest
from app.core.security import create_access_token, decode_access_token, revoke_token, is_token_revoked


class TestJwtRevocation:
    """JWT revocation (jti blacklist) added in security hardening."""

    def test_new_token_is_not_revoked(self):
        token = create_access_token("test_user")
        payload = decode_access_token(token)
        assert payload is not None
        assert payload["sub"] == "test_user"

    def test_revoked_token_decodes_to_none(self):
        token = create_access_token("test_user_2")
        payload = decode_access_token(token)
        assert payload is not None
        jti = payload["jti"]
        revoke_token(jti)
        assert decode_access_token(token) is None

    def test_is_token_revoked_returns_false_for_unknown_jti(self):
        assert is_token_revoked("nonexistent-jti-xyz") is False

    def test_is_token_revoked_returns_true_after_revoke(self):
        token = create_access_token("test_user_3")
        payload = decode_access_token(token)
        jti = payload["jti"]
        assert is_token_revoked(jti) is False
        revoke_token(jti)
        assert is_token_revoked(jti) is True

    def test_token_has_jti_field(self):
        token = create_access_token("test_user_4")
        payload = decode_access_token(token)
        assert "jti" in payload
        assert len(payload["jti"]) > 0

    def test_each_token_has_unique_jti(self):
        t1 = create_access_token("user_a")
        t2 = create_access_token("user_a")
        p1 = decode_access_token(t1)
        p2 = decode_access_token(t2)
        assert p1["jti"] != p2["jti"]
