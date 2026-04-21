import pytest

from app.platform.security.tokens import split_refresh_token


def test_split_refresh_token_rejects_malformed_values() -> None:
    for token in ("", "no-dot", ".", "session.", ".secret"):
        with pytest.raises(ValueError):
            split_refresh_token(token)


def test_split_refresh_token_accepts_valid_token() -> None:
    session_id, token_secret = split_refresh_token("session.secret")
    assert session_id == "session"
    assert token_secret == "secret"
