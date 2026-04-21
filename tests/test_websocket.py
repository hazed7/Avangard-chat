import pytest
from fastapi.testclient import TestClient
from starlette.websockets import WebSocketDisconnect

from app.ws.manager import manager
from tests.test_access_control import create_room
from tests.test_auth import auth_headers, register_user


def _ws_url(room_id: str) -> str:
    return f"/ws/{room_id}"


def _ws_subprotocols(token: str) -> list[str]:
    return ["chat.v1", f"auth.bearer.{token}"]


def test_websocket_messages_are_broadcast_and_persisted(client: TestClient):
    owner = register_user(client, "ws-owner")
    member = register_user(client, "ws-member")
    room = create_room(
        client,
        owner["access_token"],
        member_ids=[member["user"]["id"]],
        name="ws-room",
    )

    with (
        client.websocket_connect(
            _ws_url(room["id"]),
            subprotocols=_ws_subprotocols(owner["access_token"]),
        ) as owner_ws,
        client.websocket_connect(
            _ws_url(room["id"]),
            subprotocols=_ws_subprotocols(member["access_token"]),
        ) as member_ws,
    ):
        owner_ws.send_json({"text": "hello over websocket"})
        owner_event = owner_ws.receive_json()
        member_event = member_ws.receive_json()

    for event in (owner_event, member_event):
        assert event["type"] == "message"
        assert event["message"]["text"] == "hello over websocket"
        assert event["message"]["room_id"] == room["id"]
        assert event["message"]["sender_id"] == owner["user"]["id"]

    history_response = client.get(
        f"/message/room/{room['id']}",
        headers=auth_headers(owner["access_token"]),
    )
    assert history_response.status_code == 200
    assert len(history_response.json()) == 1
    assert history_response.json()[0]["text"] == "hello over websocket"


def test_websocket_rejects_non_members(client: TestClient):
    owner = register_user(client, "ws-owner-private")
    outsider = register_user(client, "ws-outsider-private")
    room = create_room(
        client,
        owner["access_token"],
        member_ids=[],
        name="private-ws-room",
    )

    with pytest.raises(WebSocketDisconnect) as exc_info:
        with client.websocket_connect(
            _ws_url(room["id"]),
            subprotocols=_ws_subprotocols(outsider["access_token"]),
        ):
            pass

    assert exc_info.value.code == 1008


def test_websocket_invalid_payload_returns_error(client: TestClient):
    owner = register_user(client, "ws-invalid-owner")
    room = create_room(
        client,
        owner["access_token"],
        member_ids=[],
        name="invalid-payload-room",
    )

    with client.websocket_connect(
        _ws_url(room["id"]),
        subprotocols=_ws_subprotocols(owner["access_token"]),
    ) as ws:
        ws.send_json({"unexpected": "payload"})
        error_event = ws.receive_json()

    assert error_event == {"type": "error", "detail": "Invalid message payload"}


def test_websocket_disconnect_cleans_up_empty_room(client: TestClient):
    owner = register_user(client, "ws-cleanup-owner")
    room = create_room(
        client,
        owner["access_token"],
        member_ids=[],
        name="cleanup-room",
    )

    assert room["id"] not in manager.rooms
    with client.websocket_connect(
        _ws_url(room["id"]),
        subprotocols=_ws_subprotocols(owner["access_token"]),
    ):
        assert room["id"] in manager.rooms
        assert len(manager.rooms[room["id"]]) == 1

    assert room["id"] not in manager.rooms
