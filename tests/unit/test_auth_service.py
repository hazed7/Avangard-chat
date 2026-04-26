import asyncio
from types import SimpleNamespace

import pytest
from fastapi import HTTPException

from app.modules.auth.service import AuthService
from app.platform.backends.dragonfly.service import now_unix
from app.platform.security.tokens import compose_refresh_token, hash_refresh_token


class FakeDragonfly:
    def __init__(self, session: dict):
        self._session = session
        self.saved_sessions: list[dict] = []
        self.lock_released = False
        self._save_calls = 0

    async def acquire_refresh_lock(self, session_id: str) -> str | None:
        return "lock-token"

    async def release_refresh_lock(self, session_id: str, token: str) -> None:
        self.lock_released = True

    async def get_refresh_session(self, session_id: str) -> dict | None:
        return dict(self._session)

    async def save_refresh_session(self, *, session: dict, ttl_seconds: int) -> None:
        self._save_calls += 1
        self.saved_sessions.append(dict(session))
        if self._save_calls == 1:
            raise HTTPException(status_code=503, detail="simulated save failure")


def test_refresh_rotation_rolls_back_new_session_when_old_revoke_fails(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    old_secret = "old-secret"
    current_ts = now_unix()
    old_session = {
        "id": "old-session",
        "user_id": "user-1",
        "token_hash": hash_refresh_token(old_secret),
        "created_at": current_ts - 10,
        "expires_at": current_ts + 3600,
        "last_used_at": None,
        "revoked_at": None,
        "replaced_by_session_id": None,
        "user_agent": "ua",
        "ip_address": "127.0.0.1",
    }
    fake_dragonfly = FakeDragonfly(session=old_session)
    service = AuthService(dragonfly=fake_dragonfly)  # type: ignore[arg-type]

    async def fake_get_user_by_id(user_id: str):
        return SimpleNamespace(id=user_id, username="alice")

    async def fake_create_refresh_session(
        *, user_id: str, user_agent: str | None, ip_address: str | None
    ):
        return (
            {
                "id": "new-session",
                "user_id": user_id,
                "token_hash": hash_refresh_token("new-secret"),
                "created_at": current_ts,
                "expires_at": current_ts + 3600,
                "last_used_at": None,
                "revoked_at": None,
                "replaced_by_session_id": None,
                "user_agent": user_agent,
                "ip_address": ip_address,
            },
            compose_refresh_token("new-session", "new-secret"),
        )

    monkeypatch.setattr(service, "_get_user_by_id", fake_get_user_by_id)
    monkeypatch.setattr(service, "_create_refresh_session", fake_create_refresh_session)

    with pytest.raises(HTTPException) as exc:
        asyncio.run(
            service.refresh(
                refresh_token=compose_refresh_token("old-session", old_secret),
                user_agent="ua",
                ip_address="127.0.0.1",
            )
        )
    assert exc.value.status_code == 503
    assert exc.value.detail == "Temporary session rotation failure"
    assert fake_dragonfly.lock_released is True
    assert len(fake_dragonfly.saved_sessions) == 2
    rollback_new = fake_dragonfly.saved_sessions[1]
    assert rollback_new["id"] == "new-session"
    assert rollback_new["revoked_at"] is not None
