from fastapi.testclient import TestClient

from app.main import app
from app.platform.http.dependencies import get_message_service, verify_token


class FakeMessageService:
    def __init__(self):
        self.deleted: tuple[str, str] | None = None

    async def delete(self, message_id: str, user_id: str) -> None:
        self.deleted = (message_id, user_id)


def test_message_delete_can_use_overridden_service_without_db(client: TestClient):
    fake_service = FakeMessageService()

    app.dependency_overrides[get_message_service] = lambda: fake_service
    app.dependency_overrides[verify_token] = lambda: {"sub": "unit-test-user"}
    try:
        response = client.delete("/message/message-123")
    finally:
        app.dependency_overrides.pop(get_message_service, None)
        app.dependency_overrides.pop(verify_token, None)

    assert response.status_code == 200
    assert response.json() == {"ok": True}
    assert fake_service.deleted == ("message-123", "unit-test-user")
