import pytest
from fastapi.testclient import TestClient
from starlette.websockets import WebSocketDisconnect

from app.config import settings
from app.ws.manager import manager
from tests.test_access_control import create_room
from tests.test_auth import auth_headers, register_user


def _ws_url(room_id: str) -> str:
    return f"/ws/{room_id}"


def _ws_subprotocols(token: str) -> list[str]:
    return ["chat.v1", f"auth.bearer.{token}"]


def _ws_create_message_event(text: str) -> dict:
    return {
        "type": "chat.message.create",
        "payload": {"text": text},
    }


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
        owner_ws.send_json(_ws_create_message_event("hello over websocket"))
        owner_event = owner_ws.receive_json()
        member_event = member_ws.receive_json()

    for event in (owner_event, member_event):
        assert event["type"] == "chat.message.created"
        assert event["payload"]["text"] == "hello over websocket"
        assert event["payload"]["room_id"] == room["id"]
        assert event["payload"]["sender_id"] == owner["user"]["id"]

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


def test_websocket_requires_chat_subprotocol(client: TestClient):
    owner = register_user(client, "ws-protocol-owner")
    room = create_room(
        client,
        owner["access_token"],
        member_ids=[],
        name="protocol-room",
    )

    with pytest.raises(WebSocketDisconnect) as exc_info:
        with client.websocket_connect(
            _ws_url(room["id"]),
            subprotocols=[f"auth.bearer.{owner['access_token']}"],
        ):
            pass

    assert exc_info.value.code == 1002


def test_websocket_legacy_payload_returns_invalid_event_error(client: TestClient):
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

    assert error_event == {
        "type": "error",
        "payload": {
            "code": "invalid_event",
            "detail": "Expected event: chat.message.create",
        },
    }


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


def test_websocket_rate_limit_blocks_spam(
    client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
):
    monkeypatch.setattr(settings, "ws_rate_limit_max_messages", 2)
    monkeypatch.setattr(settings, "ws_rate_limit_window_seconds", 60)

    owner = register_user(client, "ws-rate-limit-owner")
    room = create_room(
        client,
        owner["access_token"],
        member_ids=[],
        name="ws-rate-limit-room",
    )

    with client.websocket_connect(
        _ws_url(room["id"]),
        subprotocols=_ws_subprotocols(owner["access_token"]),
    ) as ws:
        ws.send_json(_ws_create_message_event("one"))
        first_event = ws.receive_json()
        assert first_event["type"] == "chat.message.created"

        ws.send_json(_ws_create_message_event("two"))
        second_event = ws.receive_json()
        assert second_event["type"] == "chat.message.created"

        ws.send_json(_ws_create_message_event("three"))
        error_event = ws.receive_json()
        assert error_event == {
            "type": "error",
            "payload": {
                "code": "rate_limit_exceeded",
                "detail": "Too many websocket messages. Slow down.",
            },
        }

        with pytest.raises(WebSocketDisconnect) as exc_info:
            ws.receive_json()

    assert exc_info.value.code == 1008


def test_websocket_connection_rate_limit_blocks_connect_spam(
    client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
):
    monkeypatch.setattr(settings, "ws_connect_rate_limit_max_attempts", 2)
    monkeypatch.setattr(settings, "ws_connect_rate_limit_window_seconds", 60)

    owner = register_user(client, "ws-connect-limit-owner")
    room = create_room(
        client,
        owner["access_token"],
        member_ids=[],
        name="ws-connect-limit-room",
    )

    with client.websocket_connect(
        _ws_url(room["id"]),
        subprotocols=_ws_subprotocols(owner["access_token"]),
    ):
        pass

    with client.websocket_connect(
        _ws_url(room["id"]),
        subprotocols=_ws_subprotocols(owner["access_token"]),
    ):
        pass

    with pytest.raises(WebSocketDisconnect) as exc_info:
        with client.websocket_connect(
            _ws_url(room["id"]),
            subprotocols=_ws_subprotocols(owner["access_token"]),
        ):
            pass

    assert exc_info.value.code == 1008
