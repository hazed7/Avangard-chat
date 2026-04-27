import asyncio

from fastapi.testclient import TestClient

from app.main import app
from app.modules.calls.model import CallSession
from app.modules.system.dependencies import get_livekit_service
from tests.helpers.auth import auth_headers, register_user
from tests.helpers.chat import create_room


def _ws_url(room_id: str) -> str:
    return f"/ws/{room_id}"


def _ws_subprotocols(token: str) -> list[str]:
    return ["chat.v1", f"auth.bearer.{token}"]


def _ws_receive_until(ws, event_type: str) -> dict:  # noqa: ANN001
    while True:
        event = ws.receive_json()
        if event.get("type") == event_type:
            return event


def test_call_invite_ringing_join_end_and_room_history(client: TestClient):
    owner = register_user(client, "call-owner")
    member = register_user(client, "call-member")
    room = create_room(
        client,
        owner["access_token"],
        member_ids=[member["user"]["id"]],
        name="call-room",
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
        invite_response = client.post(
            f"/call/room/{room['id']}/invite",
            headers=auth_headers(owner["access_token"]),
        )
        assert invite_response.status_code == 200
        call = invite_response.json()
        assert call["status"] == "ringing"

        owner_invited = _ws_receive_until(owner_ws, "chat.call.invited")
        member_invited = _ws_receive_until(member_ws, "chat.call.invited")
        assert owner_invited["payload"]["call_id"] == call["id"]
        assert member_invited["payload"]["call_id"] == call["id"]

        ringing_response = client.post(
            f"/call/{call['id']}/ringing",
            headers=auth_headers(member["access_token"]),
        )
        assert ringing_response.status_code == 200
        owner_ringing = _ws_receive_until(owner_ws, "chat.call.ringing")
        member_ringing = _ws_receive_until(member_ws, "chat.call.ringing")
        assert owner_ringing["payload"]["user_id"] == member["user"]["id"]
        assert member_ringing["payload"]["user_id"] == member["user"]["id"]

        owner_join = client.post(
            f"/call/{call['id']}/join",
            headers=auth_headers(owner["access_token"]),
        )
        assert owner_join.status_code == 200
        owner_join_payload = owner_join.json()
        assert owner_join_payload["livekit"]["url"] == "ws://livekit.test"
        assert (
            owner_join_payload["livekit"]["participant_identity"] == owner["user"]["id"]
        )
        assert owner_join_payload["call"]["status"] == "ringing"
        _ws_receive_until(owner_ws, "chat.call.joined")
        _ws_receive_until(member_ws, "chat.call.joined")

        member_join = client.post(
            f"/call/{call['id']}/join",
            headers=auth_headers(member["access_token"]),
        )
        assert member_join.status_code == 200
        member_join_payload = member_join.json()
        assert member_join_payload["call"]["status"] == "active"
        assert member_join_payload["livekit"]["token"] == (
            f"token-{room['id']}-{member['user']['id']}"
        )
        member_joined_owner = _ws_receive_until(owner_ws, "chat.call.joined")
        member_joined_member = _ws_receive_until(member_ws, "chat.call.joined")
        assert member_joined_owner["payload"]["user_id"] == member["user"]["id"]
        assert member_joined_member["payload"]["user_id"] == member["user"]["id"]

        active_response = client.get(
            f"/call/room/{room['id']}/active",
            headers=auth_headers(owner["access_token"]),
        )
        assert active_response.status_code == 200
        assert active_response.json()["status"] == "active"

        end_response = client.post(
            f"/call/{call['id']}/end",
            headers=auth_headers(owner["access_token"]),
        )
        assert end_response.status_code == 200
        assert end_response.json()["status"] == "ended"
        assert end_response.json()["ended_reason"] == "ended"

        owner_ended = _ws_receive_until(owner_ws, "chat.call.ended")
        member_ended = _ws_receive_until(member_ws, "chat.call.ended")
        assert owner_ended["payload"]["call_id"] == call["id"]
        assert member_ended["payload"]["call_id"] == call["id"]

    history_response = client.get(
        f"/call/room/{room['id']}/history",
        headers=auth_headers(owner["access_token"]),
    )
    assert history_response.status_code == 200
    history_payload = history_response.json()
    assert len(history_payload["items"]) == 1
    assert history_payload["items"][0]["id"] == call["id"]
    assert history_payload["items"][0]["status"] == "ended"


def test_missed_calls_can_be_acknowledged(client: TestClient):
    owner = register_user(client, "missed-owner")
    member = register_user(client, "missed-member")
    room = create_room(
        client,
        owner["access_token"],
        member_ids=[member["user"]["id"]],
        name="missed-room",
    )

    invite_response = client.post(
        f"/call/room/{room['id']}/invite",
        headers=auth_headers(owner["access_token"]),
    )
    assert invite_response.status_code == 200
    call = invite_response.json()

    end_response = client.post(
        f"/call/{call['id']}/end",
        headers=auth_headers(owner["access_token"]),
    )
    assert end_response.status_code == 200
    assert end_response.json()["ended_reason"] == "cancelled"

    missed_response = client.get(
        "/call/missed",
        headers=auth_headers(member["access_token"]),
    )
    assert missed_response.status_code == 200
    missed_payload = missed_response.json()
    assert len(missed_payload["items"]) == 1
    assert missed_payload["items"][0]["id"] == call["id"]

    ack_response = client.post(
        f"/call/{call['id']}/missed/ack",
        headers=auth_headers(member["access_token"]),
    )
    assert ack_response.status_code == 200

    missed_after_ack = client.get(
        "/call/missed",
        headers=auth_headers(member["access_token"]),
    )
    assert missed_after_ack.status_code == 200
    assert missed_after_ack.json() == {"items": [], "next_cursor": None}


def test_declining_call_ends_it_without_marking_a_missed_call(client: TestClient):
    owner = register_user(client, "decline-owner")
    member = register_user(client, "decline-member")
    room = create_room(
        client,
        owner["access_token"],
        member_ids=[member["user"]["id"]],
        name="decline-room",
    )

    invite_response = client.post(
        f"/call/room/{room['id']}/invite",
        headers=auth_headers(owner["access_token"]),
    )
    assert invite_response.status_code == 200
    call = invite_response.json()

    decline_response = client.post(
        f"/call/{call['id']}/leave",
        headers=auth_headers(member["access_token"]),
    )
    assert decline_response.status_code == 200
    assert decline_response.json()["status"] == "ended"
    assert decline_response.json()["ended_reason"] == "cancelled"

    participants = decline_response.json()["participants"]
    member_state = next(
        participant
        for participant in participants
        if participant["user_id"] == member["user"]["id"]
    )
    assert member_state["left_at"] is not None
    assert member_state["missed_at"] is None

    missed_response = client.get(
        "/call/missed",
        headers=auth_headers(member["access_token"]),
    )
    assert missed_response.status_code == 200
    assert missed_response.json() == {"items": [], "next_cursor": None}


def test_removing_last_pending_participant_ends_call_without_missed_state(
    client: TestClient,
):
    owner = register_user(client, "remove-pending-owner")
    member = register_user(client, "remove-pending-member")
    room = create_room(
        client,
        owner["access_token"],
        member_ids=[member["user"]["id"]],
        name="remove-pending-room",
    )

    invite_response = client.post(
        f"/call/room/{room['id']}/invite",
        headers=auth_headers(owner["access_token"]),
    )
    assert invite_response.status_code == 200
    call = invite_response.json()

    remove_response = client.post(
        f"/call/{call['id']}/participants/{member['user']['id']}/remove",
        headers=auth_headers(owner["access_token"]),
    )
    assert remove_response.status_code == 200
    assert remove_response.json()["status"] == "ended"
    assert remove_response.json()["ended_reason"] == "member_removed"

    member_state = next(
        participant
        for participant in remove_response.json()["participants"]
        if participant["user_id"] == member["user"]["id"]
    )
    assert member_state["left_at"] is not None
    assert member_state["missed_at"] is None

    missed_response = client.get(
        "/call/missed",
        headers=auth_headers(member["access_token"]),
    )
    assert missed_response.status_code == 200
    assert missed_response.json() == {"items": [], "next_cursor": None}


def test_call_cleanup_runs_on_member_removal_and_room_delete(client: TestClient):
    owner = register_user(client, "cleanup-owner")
    member = register_user(client, "cleanup-member")
    room = create_room(
        client,
        owner["access_token"],
        member_ids=[member["user"]["id"]],
        name="cleanup-call-room",
    )

    call_response = client.post(
        f"/call/room/{room['id']}/invite",
        headers=auth_headers(owner["access_token"]),
    )
    assert call_response.status_code == 200
    call = call_response.json()

    owner_join = client.post(
        f"/call/{call['id']}/join",
        headers=auth_headers(owner["access_token"]),
    )
    assert owner_join.status_code == 200
    member_join = client.post(
        f"/call/{call['id']}/join",
        headers=auth_headers(member["access_token"]),
    )
    assert member_join.status_code == 200

    remove_member = client.delete(
        f"/room/{room['id']}/members/{member['user']['id']}",
        headers=auth_headers(owner["access_token"]),
    )
    assert remove_member.status_code == 200

    participant_snapshot = client.get(
        f"/call/{call['id']}/participants",
        headers=auth_headers(owner["access_token"]),
    )
    assert participant_snapshot.status_code == 200
    member_state = next(
        participant
        for participant in participant_snapshot.json()["participants"]
        if participant["user_id"] == member["user"]["id"]
    )
    assert member_state["left_at"] is not None

    fake_livekit = get_livekit_service()
    assert (room["id"], member["user"]["id"]) in fake_livekit.removed_participants

    call_doc = asyncio.run(CallSession.get(call["id"]))
    assert call_doc is not None
    assert call_doc.status == "ended"
    assert call_doc.ended_reason == "member_removed"

    room_delete_owner = register_user(client, "room-delete-owner")
    room_delete_member = register_user(client, "room-delete-member")
    room_delete_room = create_room(
        client,
        room_delete_owner["access_token"],
        member_ids=[room_delete_member["user"]["id"]],
        name="room-delete-call-room",
    )
    room_delete_call_response = client.post(
        f"/call/room/{room_delete_room['id']}/invite",
        headers=auth_headers(room_delete_owner["access_token"]),
    )
    assert room_delete_call_response.status_code == 200
    room_delete_call = room_delete_call_response.json()

    delete_room = client.delete(
        f"/room/{room_delete_room['id']}",
        headers=auth_headers(room_delete_owner["access_token"]),
    )
    assert delete_room.status_code == 200
    assert room_delete_room["id"] in fake_livekit.deleted_rooms

    room_delete_call_doc = asyncio.run(CallSession.get(room_delete_call["id"]))
    assert room_delete_call_doc is not None
    assert room_delete_call_doc.status == "ended"
    assert room_delete_call_doc.ended_reason == "room_deleted"


def test_call_end_returns_503_when_livekit_room_delete_fails(client: TestClient):
    owner = register_user(client, "call-fail-owner")
    member = register_user(client, "call-fail-member")
    room = create_room(
        client,
        owner["access_token"],
        member_ids=[member["user"]["id"]],
        name="call-fail-room",
    )

    invite_response = client.post(
        f"/call/room/{room['id']}/invite",
        headers=auth_headers(owner["access_token"]),
    )
    assert invite_response.status_code == 200
    call = invite_response.json()

    class FailingLiveKitService:
        public_url = "ws://livekit.test"

        async def ping(self) -> bool:
            return True

        def room_name(self, room_id: str) -> str:
            return f"chat-room:{room_id}"

        def create_join_token(self, **kwargs):  # noqa: ANN003
            return "token", kwargs["metadata"]

        async def remove_participant(self, *, room_id: str, user_id: str) -> None:
            del room_id, user_id

        async def delete_room(self, *, room_id: str) -> None:
            del room_id
            raise RuntimeError("boom")

    app.dependency_overrides[get_livekit_service] = lambda: FailingLiveKitService()
    try:
        end_response = client.post(
            f"/call/{call['id']}/end",
            headers=auth_headers(owner["access_token"]),
        )
    finally:
        app.dependency_overrides.pop(get_livekit_service, None)

    assert end_response.status_code == 503
    assert end_response.json() == {"detail": "Temporary call service failure"}

    call_doc = asyncio.run(CallSession.get(call["id"]))
    assert call_doc is not None
    assert call_doc.status == "ringing"


def test_non_manager_cannot_force_end_call(client: TestClient):
    owner = register_user(client, "force-end-owner")
    actor = register_user(client, "force-end-actor")
    member = register_user(client, "force-end-member")
    room = create_room(
        client,
        owner["access_token"],
        member_ids=[actor["user"]["id"], member["user"]["id"]],
        name="force-end-room",
    )

    invite_response = client.post(
        f"/call/room/{room['id']}/invite",
        headers=auth_headers(owner["access_token"]),
    )
    assert invite_response.status_code == 200
    call = invite_response.json()

    end_response = client.post(
        f"/call/{call['id']}/end",
        headers=auth_headers(actor["access_token"]),
    )
    assert end_response.status_code == 403
    assert end_response.json() == {
        "detail": "You do not have permission to manage this call"
    }

    active_response = client.get(
        f"/call/room/{room['id']}/active",
        headers=auth_headers(owner["access_token"]),
    )
    assert active_response.status_code == 200
    assert active_response.json()["status"] == "ringing"


def test_room_owner_can_force_end_call_started_by_other_member(client: TestClient):
    owner = register_user(client, "owner-force-end-owner")
    initiator = register_user(client, "owner-force-end-initiator")
    member = register_user(client, "owner-force-end-member")
    room = create_room(
        client,
        owner["access_token"],
        member_ids=[initiator["user"]["id"], member["user"]["id"]],
        name="owner-force-end-room",
    )

    invite_response = client.post(
        f"/call/room/{room['id']}/invite",
        headers=auth_headers(initiator["access_token"]),
    )
    assert invite_response.status_code == 200
    call = invite_response.json()

    end_response = client.post(
        f"/call/{call['id']}/end",
        headers=auth_headers(owner["access_token"]),
    )
    assert end_response.status_code == 200
    assert end_response.json()["status"] == "ended"
    assert end_response.json()["ended_reason"] == "cancelled"


def test_initiator_leave_before_answer_publishes_cancelled_reason(client: TestClient):
    owner = register_user(client, "initiator-cancel-owner")
    member = register_user(client, "initiator-cancel-member")
    room = create_room(
        client,
        owner["access_token"],
        member_ids=[member["user"]["id"]],
        name="initiator-cancel-room",
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
        invite_response = client.post(
            f"/call/room/{room['id']}/invite",
            headers=auth_headers(owner["access_token"]),
        )
        assert invite_response.status_code == 200
        call = invite_response.json()

        leave_response = client.post(
            f"/call/{call['id']}/leave",
            headers=auth_headers(owner["access_token"]),
        )
        assert leave_response.status_code == 200
        assert leave_response.json()["status"] == "ended"
        assert leave_response.json()["ended_reason"] == "cancelled"

        owner_left = _ws_receive_until(owner_ws, "chat.call.left")
        member_left = _ws_receive_until(member_ws, "chat.call.left")
        assert owner_left["payload"]["reason"] == "cancelled"
        assert member_left["payload"]["reason"] == "cancelled"


def test_invite_conflicts_when_call_is_already_active(client: TestClient):
    owner = register_user(client, "conflict-owner")
    member = register_user(client, "conflict-member")
    room = create_room(
        client,
        owner["access_token"],
        member_ids=[member["user"]["id"]],
        name="conflict-room",
    )

    first_invite = client.post(
        f"/call/room/{room['id']}/invite",
        headers=auth_headers(owner["access_token"]),
    )
    assert first_invite.status_code == 200

    second_invite = client.post(
        f"/call/room/{room['id']}/invite",
        headers=auth_headers(owner["access_token"]),
    )
    assert second_invite.status_code == 409
    assert second_invite.json() == {"detail": "A call is already active"}


def test_join_ended_call_returns_conflict(client: TestClient):
    owner = register_user(client, "join-ended-owner")
    member = register_user(client, "join-ended-member")
    room = create_room(
        client,
        owner["access_token"],
        member_ids=[member["user"]["id"]],
        name="join-ended-room",
    )

    invite_response = client.post(
        f"/call/room/{room['id']}/invite",
        headers=auth_headers(owner["access_token"]),
    )
    assert invite_response.status_code == 200
    call = invite_response.json()

    end_response = client.post(
        f"/call/{call['id']}/end",
        headers=auth_headers(owner["access_token"]),
    )
    assert end_response.status_code == 200

    join_response = client.post(
        f"/call/{call['id']}/join",
        headers=auth_headers(member["access_token"]),
    )
    assert join_response.status_code == 409
    assert join_response.json() == {"detail": "Call has already ended"}


def test_call_history_cursor_paginates_and_validates_input(client: TestClient):
    owner = register_user(client, "history-cursor-owner")
    member = register_user(client, "history-cursor-member")
    room = create_room(
        client,
        owner["access_token"],
        member_ids=[member["user"]["id"]],
        name="history-cursor-room",
    )

    call_ids: list[str] = []
    for _ in range(3):
        invite_response = client.post(
            f"/call/room/{room['id']}/invite",
            headers=auth_headers(owner["access_token"]),
        )
        assert invite_response.status_code == 200
        call_id = invite_response.json()["id"]
        call_ids.append(call_id)

        end_response = client.post(
            f"/call/{call_id}/end",
            headers=auth_headers(owner["access_token"]),
        )
        assert end_response.status_code == 200

    first_page = client.get(
        f"/call/room/{room['id']}/history?limit=2",
        headers=auth_headers(owner["access_token"]),
    )
    assert first_page.status_code == 200
    first_payload = first_page.json()
    assert len(first_payload["items"]) == 2
    assert first_payload["next_cursor"] is not None

    second_page = client.get(
        f"/call/room/{room['id']}/history?limit=2&cursor={first_payload['next_cursor']}",
        headers=auth_headers(owner["access_token"]),
    )
    assert second_page.status_code == 200
    second_payload = second_page.json()
    assert len(second_payload["items"]) == 1
    assert second_payload["next_cursor"] is None

    seen_ids = [
        item["id"] for item in [*first_payload["items"], *second_payload["items"]]
    ]
    assert sorted(seen_ids) == sorted(call_ids)

    invalid_cursor = client.get(
        f"/call/room/{room['id']}/history?cursor=not-a-valid-cursor",
        headers=auth_headers(owner["access_token"]),
    )
    assert invalid_cursor.status_code == 400
    assert invalid_cursor.json() == {"detail": "Invalid cursor"}


def test_non_manager_cannot_remove_participant_from_call(client: TestClient):
    owner = register_user(client, "remove-authz-owner")
    actor = register_user(client, "remove-authz-actor")
    target = register_user(client, "remove-authz-target")
    room = create_room(
        client,
        owner["access_token"],
        member_ids=[actor["user"]["id"], target["user"]["id"]],
        name="remove-authz-room",
    )

    invite_response = client.post(
        f"/call/room/{room['id']}/invite",
        headers=auth_headers(owner["access_token"]),
    )
    assert invite_response.status_code == 200
    call = invite_response.json()

    remove_response = client.post(
        f"/call/{call['id']}/participants/{target['user']['id']}/remove",
        headers=auth_headers(actor["access_token"]),
    )
    assert remove_response.status_code == 403
    assert remove_response.json() == {
        "detail": "You do not have permission to manage this call"
    }


def test_missed_call_ack_works_after_member_removed_from_room(client: TestClient):
    owner = register_user(client, "ack-removed-owner")
    member = register_user(client, "ack-removed-member")
    room = create_room(
        client,
        owner["access_token"],
        member_ids=[member["user"]["id"]],
        name="ack-removed-room",
    )

    invite_response = client.post(
        f"/call/room/{room['id']}/invite",
        headers=auth_headers(owner["access_token"]),
    )
    assert invite_response.status_code == 200
    call = invite_response.json()

    end_response = client.post(
        f"/call/{call['id']}/end",
        headers=auth_headers(owner["access_token"]),
    )
    assert end_response.status_code == 200

    remove_member_response = client.delete(
        f"/room/{room['id']}/members/{member['user']['id']}",
        headers=auth_headers(owner["access_token"]),
    )
    assert remove_member_response.status_code == 200

    ack_response = client.post(
        f"/call/{call['id']}/missed/ack",
        headers=auth_headers(member["access_token"]),
    )
    assert ack_response.status_code == 200

    missed_response = client.get(
        "/call/missed",
        headers=auth_headers(member["access_token"]),
    )
    assert missed_response.status_code == 200
    assert missed_response.json() == {"items": [], "next_cursor": None}


def test_missed_call_ack_rejects_non_participant(client: TestClient):
    owner = register_user(client, "ack-non-participant-owner")
    member = register_user(client, "ack-non-participant-member")
    outsider = register_user(client, "ack-non-participant-outsider")
    room = create_room(
        client,
        owner["access_token"],
        member_ids=[member["user"]["id"]],
        name="ack-non-participant-room",
    )

    invite_response = client.post(
        f"/call/room/{room['id']}/invite",
        headers=auth_headers(owner["access_token"]),
    )
    assert invite_response.status_code == 200
    call = invite_response.json()

    end_response = client.post(
        f"/call/{call['id']}/end",
        headers=auth_headers(owner["access_token"]),
    )
    assert end_response.status_code == 200

    ack_response = client.post(
        f"/call/{call['id']}/missed/ack",
        headers=auth_headers(outsider["access_token"]),
    )
    assert ack_response.status_code == 403
    assert ack_response.json() == {
        "detail": "You do not have permission to access this call"
    }


def test_openapi_includes_call_routes(client: TestClient):
    response = client.get("/openapi.json")
    assert response.status_code == 200
    schema = response.json()

    paths = schema["paths"]
    operation_refs = [
        ("/call/room/{room_id}/invite", "post"),
        ("/call/room/{room_id}/active", "get"),
        ("/call/{call_id}/ringing", "post"),
        ("/call/{call_id}/join", "post"),
        ("/call/{call_id}/leave", "post"),
        ("/call/{call_id}/end", "post"),
        ("/call/{call_id}/participants", "get"),
        ("/call/{call_id}/participants/{target_user_id}/remove", "post"),
        ("/call/room/{room_id}/history", "get"),
        ("/call/missed", "get"),
        ("/call/{call_id}/missed/ack", "post"),
    ]
    for path, method in operation_refs:
        responses = paths[path][method]["responses"]
        assert "200" in responses
        assert "application/json" in responses["200"]["content"]
