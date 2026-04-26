from fastapi.testclient import TestClient

from tests.helpers.auth import auth_headers, register_user
from tests.helpers.chat import create_room


def _ws_url(room_id: str) -> str:
    return f"/ws/{room_id}"


def _ws_subprotocols(token: str) -> list[str]:
    return ["chat.v1", f"auth.bearer.{token}"]


def test_user_endpoints_reflect_live_websocket_presence(client: TestClient):
    owner = register_user(client, "presence-owner")
    viewer = register_user(client, "presence-viewer")
    room = create_room(
        client,
        owner["access_token"],
        member_ids=[],
        name="presence-room",
    )

    offline_response = client.get(
        f"/user/{owner['user']['id']}",
        headers=auth_headers(viewer["access_token"]),
    )
    assert offline_response.status_code == 200
    assert offline_response.json()["is_online"] is False

    with client.websocket_connect(
        _ws_url(room["id"]),
        subprotocols=_ws_subprotocols(owner["access_token"]),
    ):
        me_response = client.get(
            "/user/me",
            headers=auth_headers(owner["access_token"]),
        )
        assert me_response.status_code == 200
        assert me_response.json()["is_online"] is True

        other_response = client.get(
            f"/user/{owner['user']['id']}",
            headers=auth_headers(viewer["access_token"]),
        )
        assert other_response.status_code == 200
        assert other_response.json()["is_online"] is True

    after_disconnect = client.get(
        "/user/me",
        headers=auth_headers(owner["access_token"]),
    )
    assert after_disconnect.status_code == 200
