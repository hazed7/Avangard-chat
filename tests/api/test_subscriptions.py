from fastapi.testclient import TestClient

from app.modules.ai_assist.enums import RewriteStyle
from app.modules.ai_assist.schemas import RewriteResponse
from app.modules.ai_assist.service import AIAssistService
from tests.helpers.auth import auth_headers, register_user


def test_subscription_status_defaults_to_free(client: TestClient):
    auth = register_user(client, "sub-free")

    response = client.get(
        "/subscriptions/status",
        headers=auth_headers(auth["access_token"]),
    )

    assert response.status_code == 200
    assert response.json()["plan_id"] == "free"
    assert response.json()["features"] == ["basic_messaging"]


def test_ai_assist_requires_paid_feature(client: TestClient):
    auth = register_user(client, "sub-ai-denied")

    response = client.post(
        "/ai_assist/ai/rewrite",
        headers=auth_headers(auth["access_token"]),
        json={"text": "hello", "style": "formal"},
    )

    assert response.status_code == 403


def test_paid_subscription_unlocks_ai_assist(client: TestClient, monkeypatch):
    auth = register_user(client, "sub-ai-allowed")
    monkeypatch.setattr(
        "app.modules.subscriptions.service.settings.subscription_self_activation_enabled",
        True,
    )

    async def fake_rewrite(text: str, style: RewriteStyle) -> RewriteResponse:
        return RewriteResponse(original=text, rewritten="Hello.", style=style)

    monkeypatch.setattr(AIAssistService, "rewrite", fake_rewrite)

    activate_response = client.post(
        "/subscriptions/activate",
        headers=auth_headers(auth["access_token"]),
        json={"plan_id": "premium_monthly", "days": 30},
    )
    assert activate_response.status_code == 200
    assert "ai_assist" in activate_response.json()["features"]

    rewrite_response = client.post(
        "/ai_assist/ai/rewrite",
        headers=auth_headers(auth["access_token"]),
        json={"text": "hello", "style": "formal"},
    )

    assert rewrite_response.status_code == 200
    assert rewrite_response.json()["rewritten"] == "Hello."


def test_invalid_subscription_plan_returns_422(client: TestClient, monkeypatch):
    auth = register_user(client, "sub-invalid")
    monkeypatch.setattr(
        "app.modules.subscriptions.service.settings.subscription_self_activation_enabled",
        True,
    )

    response = client.post(
        "/subscriptions/activate",
        headers=auth_headers(auth["access_token"]),
        json={"plan_id": "free", "days": 30},
    )

    assert response.status_code == 422
    assert response.json()["detail"] == "Invalid paid plan"


def test_cancel_subscription_removes_paid_features(client: TestClient, monkeypatch):
    auth = register_user(client, "sub-cancel")
    monkeypatch.setattr(
        "app.modules.subscriptions.service.settings.subscription_self_activation_enabled",
        True,
    )

    activate_response = client.post(
        "/subscriptions/activate",
        headers=auth_headers(auth["access_token"]),
        json={"plan_id": "premium_monthly", "days": 30},
    )
    assert activate_response.status_code == 200

    cancel_response = client.post(
        "/subscriptions/cancel",
        headers=auth_headers(auth["access_token"]),
    )
    assert cancel_response.status_code == 200
    assert cancel_response.json()["plan_id"] == "free"

    status_response = client.get(
        "/subscriptions/status",
        headers=auth_headers(auth["access_token"]),
    )
    assert status_response.status_code == 200
    assert status_response.json()["features"] == ["basic_messaging"]


def test_subscription_activation_is_disabled_by_default(client: TestClient):
    auth = register_user(client, "sub-activation-disabled")

    response = client.post(
        "/subscriptions/activate",
        headers=auth_headers(auth["access_token"]),
        json={"plan_id": "premium_monthly", "days": 30},
    )

    assert response.status_code == 403
    assert response.json()["detail"] == "Subscription activation is disabled"
