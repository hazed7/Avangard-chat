from fastapi.testclient import TestClient

from tests.helpers.auth import auth_headers, register_user
from tests.helpers.chat import create_message, create_room


def test_room_and_message_access_is_limited_to_members(client: TestClient):
    owner = register_user(client, "owner")
    member = register_user(client, "member")
    outsider = register_user(client, "outsider")

    room = create_room(
        client,
        owner["access_token"],
        member_ids=[member["user"]["id"]],
    )

    room_response = client.get(
        f"/room/{room['id']}",
        headers=auth_headers(member["access_token"]),
    )
    assert room_response.status_code == 200

    outsider_room_response = client.get(
        f"/room/{room['id']}",
        headers=auth_headers(outsider["access_token"]),
    )
    assert outsider_room_response.status_code == 403

    member_message = create_message(
        client,
        member["access_token"],
        room["id"],
        text="member hello",
    )
    assert member_message["text"] == "member hello"

    history_response = client.get(
        f"/message/room/{room['id']}",
        headers=auth_headers(owner["access_token"]),
    )
    assert history_response.status_code == 200
    assert len(history_response.json()) == 1

    outsider_send_response = client.post(
        "/message",
        headers=auth_headers(outsider["access_token"]),
        json={"room_id": room["id"], "text": "intrusion"},
    )
    assert outsider_send_response.status_code == 403

    outsider_history_response = client.get(
        f"/message/room/{room['id']}",
        headers=auth_headers(outsider["access_token"]),
    )
    assert outsider_history_response.status_code == 403


def test_only_message_owner_and_room_creator_can_mutate(client: TestClient):
    owner = register_user(client, "roomowner")
    member = register_user(client, "roommember")
    outsider = register_user(client, "roomoutsider")

    room = create_room(
        client,
        owner["access_token"],
        member_ids=[member["user"]["id"]],
        name="locked-room",
    )
    message = create_message(
        client,
        member["access_token"],
        room["id"],
        text="original text",
    )

    owner_edit_response = client.patch(
        f"/message/{message['id']}",
        headers=auth_headers(owner["access_token"]),
        json={"text": "owner edit"},
    )
    assert owner_edit_response.status_code == 403

    outsider_delete_message_response = client.delete(
        f"/message/{message['id']}",
        headers=auth_headers(outsider["access_token"]),
    )
    assert outsider_delete_message_response.status_code == 403

    member_delete_room_response = client.delete(
        f"/room/{room['id']}",
        headers=auth_headers(member["access_token"]),
    )
    assert member_delete_room_response.status_code == 403

    owner_delete_room_response = client.delete(
        f"/room/{room['id']}",
        headers=auth_headers(owner["access_token"]),
    )
    assert owner_delete_room_response.status_code == 200


def test_message_owner_can_edit_and_delete_their_message(client: TestClient):
    owner = register_user(client, "editable-owner")
    room = create_room(
        client,
        owner["access_token"],
        member_ids=[],
        name="editable-room",
    )
    message = create_message(
        client,
        owner["access_token"],
        room["id"],
        text="draft",
    )

    edit_response = client.patch(
        f"/message/{message['id']}",
        headers=auth_headers(owner["access_token"]),
        json={"text": "published"},
    )
    assert edit_response.status_code == 200
    assert edit_response.json()["text"] == "published"
    assert edit_response.json()["is_edited"] is True

    delete_response = client.delete(
        f"/message/{message['id']}",
        headers=auth_headers(owner["access_token"]),
    )
    assert delete_response.status_code == 200
    assert delete_response.json() == {"ok": True}


def test_missing_room_and_message_return_404(client: TestClient):
    user = register_user(client, "missing-records-user")
    missing_id = "507f1f77bcf86cd799439011"

    room_response = client.get(
        f"/room/{missing_id}",
        headers=auth_headers(user["access_token"]),
    )
    assert room_response.status_code == 404

    history_response = client.get(
        f"/message/room/{missing_id}",
        headers=auth_headers(user["access_token"]),
    )
    assert history_response.status_code == 404

    send_response = client.post(
        "/message",
        headers=auth_headers(user["access_token"]),
        json={"room_id": missing_id, "text": "hello"},
    )
    assert send_response.status_code == 404

    edit_response = client.patch(
        f"/message/{missing_id}",
        headers=auth_headers(user["access_token"]),
        json={"text": "updated"},
    )
    assert edit_response.status_code == 404

    delete_response = client.delete(
        f"/message/{missing_id}",
        headers=auth_headers(user["access_token"]),
    )
    assert delete_response.status_code == 404


def test_message_history_is_sorted_and_paginates_stably(client: TestClient):
    owner = register_user(client, "history-owner")
    room = create_room(
        client,
        owner["access_token"],
        member_ids=[],
        name="history-room",
    )

    first = create_message(
        client,
        owner["access_token"],
        room["id"],
        text="first",
    )
    second = create_message(
        client,
        owner["access_token"],
        room["id"],
        text="second",
    )

    full_history_response = client.get(
        f"/message/room/{room['id']}",
        headers=auth_headers(owner["access_token"]),
    )
    assert full_history_response.status_code == 200
    full_history = full_history_response.json()
    assert [item["id"] for item in full_history] == [first["id"], second["id"]]

    paged_history_response = client.get(
        f"/message/room/{room['id']}?limit=1&offset=1",
        headers=auth_headers(owner["access_token"]),
    )
    assert paged_history_response.status_code == 200
    paged_history = paged_history_response.json()
    assert len(paged_history) == 1
    assert paged_history[0]["id"] == second["id"]


def test_users_can_only_list_their_own_rooms(client: TestClient):
    alice = register_user(client, "alice-rooms")
    bob = register_user(client, "bob-rooms")

    create_room(
        client,
        alice["access_token"],
        member_ids=[],
        name="alice-room",
    )

    own_rooms_response = client.get(
        f"/room/user/{alice['user']['id']}",
        headers=auth_headers(alice["access_token"]),
    )
    assert own_rooms_response.status_code == 200
    assert len(own_rooms_response.json()) == 1

    other_rooms_response = client.get(
        f"/room/user/{alice['user']['id']}",
        headers=auth_headers(bob["access_token"]),
    )
    assert other_rooms_response.status_code == 403
