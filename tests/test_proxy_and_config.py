import pytest
from pydantic import ValidationError

from app.core.client_ip import resolve_client_ip
from app.core.config import ProxySettings, Settings


def _base_settings_kwargs() -> dict[str, str]:
    return {
        "mongodb_url": "mongodb://localhost:27017",
        "jwt_secret_key": "access-secret",
        "refresh_token_secret_key": "refresh-secret",
    }


def test_client_ip_ignores_forwarded_headers_when_disabled() -> None:
    ip = resolve_client_ip(
        peer_ip="10.1.1.3",
        headers={"x-forwarded-for": "203.0.113.9"},
        proxy=ProxySettings(
            trust_forwarded_headers=False,
            trusted_proxy_cidrs=("10.0.0.0/8",),
        ),
    )
    assert ip == "10.1.1.3"


def test_client_ip_uses_x_forwarded_for_only_from_trusted_proxy() -> None:
    ip = resolve_client_ip(
        peer_ip="10.1.1.3",
        headers={"x-forwarded-for": "203.0.113.9, 198.51.100.7"},
        proxy=ProxySettings(
            trust_forwarded_headers=True,
            trusted_proxy_cidrs=("10.0.0.0/8", "198.51.100.0/24"),
        ),
    )
    assert ip == "203.0.113.9"


def test_client_ip_ignores_spoofed_forwarded_chain_from_untrusted_peer() -> None:
    ip = resolve_client_ip(
        peer_ip="203.0.113.55",
        headers={"x-forwarded-for": "198.51.100.1"},
        proxy=ProxySettings(
            trust_forwarded_headers=True,
            trusted_proxy_cidrs=("10.0.0.0/8",),
        ),
    )
    assert ip == "203.0.113.55"


def test_client_ip_falls_back_to_x_real_ip_for_trusted_proxy() -> None:
    ip = resolve_client_ip(
        peer_ip="10.1.1.3",
        headers={"x-real-ip": "198.51.100.25"},
        proxy=ProxySettings(
            trust_forwarded_headers=True,
            trusted_proxy_cidrs=("10.0.0.0/8",),
        ),
    )
    assert ip == "198.51.100.25"


def test_settings_reject_invalid_cookie_samesite() -> None:
    with pytest.raises(ValidationError):
        Settings(
            **_base_settings_kwargs(),
            refresh_cookie_samesite="invalid",
        )


def test_settings_reject_invalid_dragonfly_fail_policy() -> None:
    with pytest.raises(ValidationError):
        Settings(
            **_base_settings_kwargs(),
            dragonfly_fail_policy_rate_limit="OPEN",
        )


def test_settings_accept_trusted_proxy_cidrs_csv() -> None:
    config = Settings(
        **_base_settings_kwargs(),
        trusted_proxy_cidrs="10.0.0.0/8,192.168.0.0/16",
    )
    assert len(config.trusted_proxy_cidrs) == 2
