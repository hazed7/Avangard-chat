import asyncio
from datetime import UTC, datetime, timedelta

import pytest
from fastapi import HTTPException

from app.modules.subscriptions.dependencies import (
    require_active_subscription,
    require_feature,
)
from app.modules.subscriptions.models import SubscriptionStatus
from app.modules.subscriptions.service import SubscriptionService, _as_utc


class _FakeSubscription:
    def __init__(
        self,
        *,
        plan_id: str = "premium_monthly",
        status: SubscriptionStatus = SubscriptionStatus.ACTIVE,
        current_period_end: datetime | None = None,
    ) -> None:
        self.plan_id = plan_id
        self.status = status
        self.current_period_end = current_period_end
        self.updated_at: datetime | None = None
        self.saved = False

    async def save(self) -> None:
        self.saved = True


class _FakeService:
    def __init__(
        self,
        *,
        sub=None,
        features: list[str] | None = None,
    ) -> None:
        self.sub = sub
        self.features = features or []

    async def get_active_subscription(self, user_id: str):
        assert user_id == "user-1"
        return self.sub

    async def get_user_features(self, user_id: str) -> list[str]:
        assert user_id == "user-1"
        return self.features


def test_as_utc_preserves_aware_datetimes() -> None:
    value = datetime.now(UTC)

    assert _as_utc(value) == value


def test_get_active_subscription_expires_past_subscription(monkeypatch) -> None:
    sub = _FakeSubscription(
        current_period_end=datetime.now(UTC).replace(tzinfo=None) - timedelta(days=1)
    )
    service = SubscriptionService()

    async def fake_get_user_subscription(user_id: str):
        assert user_id == "user-1"
        return sub

    monkeypatch.setattr(service, "get_user_subscription", fake_get_user_subscription)

    result = asyncio.run(service.get_active_subscription("user-1"))

    assert result is None
    assert sub.status == SubscriptionStatus.EXPIRED
    assert sub.saved is True


def test_get_active_subscription_ignores_inactive_subscription(monkeypatch) -> None:
    sub = _FakeSubscription(status=SubscriptionStatus.CANCELED)
    service = SubscriptionService()

    async def fake_get_user_subscription(user_id: str):
        assert user_id == "user-1"
        return sub

    monkeypatch.setattr(service, "get_user_subscription", fake_get_user_subscription)

    assert asyncio.run(service.get_active_subscription("user-1")) is None
    assert sub.saved is False


def test_activate_subscription_rejects_non_positive_days(monkeypatch) -> None:
    monkeypatch.setattr(
        "app.modules.subscriptions.service.settings.subscription_self_activation_enabled",
        True,
    )

    with pytest.raises(HTTPException) as exc:
        asyncio.run(
            SubscriptionService().activate_subscription(
                user_id="user-1",
                plan_id="premium_monthly",
                days=0,
            )
        )

    assert exc.value.status_code == 422
    assert exc.value.detail == "Subscription days must be positive"


def test_cancel_subscription_returns_404_without_active_subscription(
    monkeypatch,
) -> None:
    service = SubscriptionService()

    async def fake_get_active_subscription(user_id: str):
        assert user_id == "user-1"
        return None

    monkeypatch.setattr(
        service, "get_active_subscription", fake_get_active_subscription
    )

    with pytest.raises(HTTPException) as exc:
        asyncio.run(service.cancel_subscription("user-1"))

    assert exc.value.status_code == 404
    assert exc.value.detail == "No active subscription"


def test_require_active_subscription_rejects_missing_subject() -> None:
    dependency = require_active_subscription

    with pytest.raises(HTTPException) as exc:
        asyncio.run(dependency(user={}, service=_FakeService()))

    assert exc.value.status_code == 401


def test_require_active_subscription_rejects_free_user() -> None:
    with pytest.raises(HTTPException) as exc:
        asyncio.run(
            require_active_subscription(
                user={"sub": "user-1"},
                service=_FakeService(sub=None),
            )
        )

    assert exc.value.status_code == 403
    assert exc.value.detail == "Active subscription required"


def test_require_active_subscription_returns_subscription() -> None:
    sub = _FakeSubscription()

    result = asyncio.run(
        require_active_subscription(
            user={"sub": "user-1"},
            service=_FakeService(sub=sub),
        )
    )

    assert result is sub


def test_require_feature_rejects_missing_subject() -> None:
    dependency = require_feature("ai_assist")

    with pytest.raises(HTTPException) as exc:
        asyncio.run(dependency(user={}, service=_FakeService()))

    assert exc.value.status_code == 401


def test_require_feature_allows_enabled_feature() -> None:
    dependency = require_feature("ai_assist")

    assert (
        asyncio.run(
            dependency(
                user={"sub": "user-1"},
                service=_FakeService(features=["ai_assist"]),
            )
        )
        is None
    )
