from fastapi.testclient import TestClient

from tests.helpers.auth import auth_headers, register_user


def _assert_exact_keys(payload: dict, keys: set[str]) -> None:
    assert set(payload.keys()) == keys


ROOM_KEYS = {
    "id",
    "name",
    "is_group",
    "member_ids",
    "created_by_id",
    "admin_ids",
    "avatar_object_path",
    "is_archived",
    "is_pinned",
    "mute_forever",
    "muted_until",
    "created_at",
    "last_message_at",
    "last_message_preview",
}

MESSAGE_KEYS = {
    "id",
    "room_id",
    "sender_id",
    "text",
    "message_type",
    "mentioned_user_ids",
    "reactions",
    "is_edited",
    "edited_at",
    "is_deleted",
    "read_by",
    "created_at",
    "attachments",
    "original_sender_id",
}


def test_rooms_and_messages_contract_shapes(client: TestClient):
    owner = register_user(client, "contract-owner")
    member = register_user(client, "contract-member")
    peer = register_user(client, "contract-peer")

    group_response = client.post(
        "/room/group",
        headers=auth_headers(owner["access_token"]),
        json={"name": "contract-group", "member_ids": [member["user"]["id"]]},
    )
    assert group_response.status_code == 200
    group = group_response.json()
    _assert_exact_keys(
        group,
        ROOM_KEYS,
    )

    dm_response = client.post(
        "/room/dm",
        headers=auth_headers(owner["access_token"]),
        json={"user_id": peer["user"]["id"]},
    )
    assert dm_response.status_code == 200
    dm = dm_response.json()
    _assert_exact_keys(
        dm,
        ROOM_KEYS,
    )

    get_room_response = client.get(
        f"/room/{group['id']}",
        headers=auth_headers(owner["access_token"]),
    )
    assert get_room_response.status_code == 200
    _assert_exact_keys(
        get_room_response.json(),
        ROOM_KEYS,
    )

    add_member_response = client.post(
        f"/room/{group['id']}/members",
        headers=auth_headers(owner["access_token"]),
        json={"user_id": peer["user"]["id"]},
    )
    assert add_member_response.status_code == 200
    _assert_exact_keys(
        add_member_response.json(),
        ROOM_KEYS,
    )

    remove_member_response = client.delete(
        f"/room/{group['id']}/members/{peer['user']['id']}",
        headers=auth_headers(owner["access_token"]),
    )
    assert remove_member_response.status_code == 200
    _assert_exact_keys(
        remove_member_response.json(),
        ROOM_KEYS,
    )

    list_rooms_response = client.get(
        f"/room/user/{owner['user']['id']}",
        headers=auth_headers(owner["access_token"]),
    )
    assert list_rooms_response.status_code == 200
    list_payload = list_rooms_response.json()
    _assert_exact_keys(list_payload, {"groups", "dms", "archived", "next_cursor"})
    assert all(
        set(room.keys()) == ROOM_KEYS
        for room in list_payload["groups"]
        + list_payload["dms"]
        + list_payload["archived"]
    )

    send_message_response = client.post(
        "/message",
        headers=auth_headers(owner["access_token"]),
        json={"room_id": group["id"], "text": "contract message"},
    )
    assert send_message_response.status_code == 200
    message = send_message_response.json()
    _assert_exact_keys(
        message,
        MESSAGE_KEYS,
    )

    history_response = client.get(
        f"/message/room/{group['id']}",
        headers=auth_headers(owner["access_token"]),
    )
    assert history_response.status_code == 200
    history_payload = history_response.json()
    _assert_exact_keys(history_payload, {"items", "next_cursor"})
    assert len(history_payload["items"]) == 1

    search_response = client.get(
        "/message/search?q=contract",
        headers=auth_headers(owner["access_token"]),
    )
    assert search_response.status_code == 200
    search_payload = search_response.json()
    _assert_exact_keys(search_payload, {"items", "next_cursor"})

    mark_read_response = client.post(
        f"/message/{message['id']}/read",
        headers=auth_headers(member["access_token"]),
    )
    assert mark_read_response.status_code == 200
    _assert_exact_keys(
        mark_read_response.json(),
        MESSAGE_KEYS,
    )

    unread_response = client.get(
        "/message/unread",
        headers=auth_headers(member["access_token"]),
    )
    assert unread_response.status_code == 200
    _assert_exact_keys(unread_response.json(), {"total", "by_room"})

    mark_room_read_response = client.post(
        f"/message/room/{group['id']}/read",
        headers=auth_headers(member["access_token"]),
    )
    assert mark_room_read_response.status_code == 200
    _assert_exact_keys(mark_room_read_response.json(), {"ok", "marked_count"})

    edit_response = client.patch(
        f"/message/{message['id']}",
        headers=auth_headers(owner["access_token"]),
        json={"text": "contract message edited"},
    )
    assert edit_response.status_code == 200
    _assert_exact_keys(
        edit_response.json(),
        MESSAGE_KEYS,
    )

    delete_message_response = client.delete(
        f"/message/{message['id']}",
        headers=auth_headers(owner["access_token"]),
    )
    assert delete_message_response.status_code == 200
    assert delete_message_response.json() == {"ok": True}

    delete_room_response = client.delete(
        f"/room/{group['id']}",
        headers=auth_headers(owner["access_token"]),
    )
    assert delete_room_response.status_code == 200
    assert delete_room_response.json() == {"ok": True}


def test_openapi_rooms_and_messages_contracts_are_explicit(client: TestClient):
    response = client.get("/openapi.json")
    assert response.status_code == 200
    schema = response.json()

    paths = schema["paths"]
    operation_refs = [
        ("/room/group", "post"),
        ("/room/dm", "post"),
        ("/room/{room_id}", "get"),
        ("/room/{room_id}/members", "post"),
        ("/room/{room_id}/members/{user_id}", "delete"),
        ("/room/user/{user_id}", "get"),
        ("/room/{room_id}", "delete"),
        ("/message", "post"),
        ("/message/voice", "post"),
        ("/room/{room_id}", "patch"),
        ("/room/{room_id}/avatar", "post"),
        ("/room/{room_id}/avatar", "delete"),
        ("/room/{room_id}/admins", "post"),
        ("/room/{room_id}/admins/{user_id}", "delete"),
        ("/room/{room_id}/preferences", "patch"),
        ("/room/{room_id}/invite-link", "post"),
        ("/room/{room_id}/invite-link", "delete"),
        ("/room/join/{token}", "post"),
        ("/room/{room_id}/pins/{message_id}", "post"),
        ("/room/{room_id}/pins", "get"),
        ("/room/{room_id}/pins/{message_id}", "delete"),
        ("/message/room/{room_id}", "get"),
        ("/message/search", "get"),
        ("/message/{message_id}/read", "post"),
        ("/message/room/{room_id}/read", "post"),
        ("/message/unread", "get"),
        ("/message/{message_id}", "patch"),
        ("/message/{message_id}/reaction", "post"),
        ("/message/{message_id}", "delete"),
    ]

    for path, method in operation_refs:
        responses = paths[path][method]["responses"]
        assert "200" in responses
        assert "content" in responses["200"]
        assert "application/json" in responses["200"]["content"]
        assert "schema" in responses["200"]["content"]["application/json"]
