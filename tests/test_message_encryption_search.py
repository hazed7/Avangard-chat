import asyncio

from app.model.message import Message
from tests.test_access_control import create_message, create_room
from tests.test_auth import auth_headers, register_user


def test_messages_are_encrypted_at_rest(client):
    owner = register_user(client, "encrypted-owner")
    room = create_room(
        client,
        owner["access_token"],
        member_ids=[],
        name="encrypted-room",
    )

    sent = create_message(
        client,
        owner["access_token"],
        room["id"],
        text="super secret text",
    )
    stored = asyncio.run(Message.get(sent["id"]))
    assert stored is not None
    assert stored.text_ciphertext
    assert stored.text_nonce
    assert stored.text_key_id == "v1"
    assert stored.text_aad
    assert "super secret text" not in stored.model_dump_json()
    assert not hasattr(stored, "text")


def test_message_search_respects_room_access(client):
    owner = register_user(client, "search-owner")
    member = register_user(client, "search-member")
    outsider = register_user(client, "search-outsider")

    private_room = create_room(
        client,
        owner["access_token"],
        member_ids=[member["user"]["id"]],
        name="search-private-room",
    )
    outsider_room = create_room(
        client,
        outsider["access_token"],
        member_ids=[],
        name="search-outsider-room",
    )

    private_message = create_message(
        client,
        owner["access_token"],
        private_room["id"],
        text="alpha bravo",
    )
    create_message(
        client,
        outsider["access_token"],
        outsider_room["id"],
        text="alpha outsider",
    )

    owner_search = client.get(
        "/message/search?q=alpha",
        headers=auth_headers(owner["access_token"]),
    )
    assert owner_search.status_code == 200
    owner_result_ids = [message["id"] for message in owner_search.json()]
    assert private_message["id"] in owner_result_ids

    outsider_search = client.get(
        "/message/search?q=alpha",
        headers=auth_headers(outsider["access_token"]),
    )
    assert outsider_search.status_code == 200
    outsider_result_ids = [message["id"] for message in outsider_search.json()]
    assert private_message["id"] not in outsider_result_ids

    unauthorized_scope = client.get(
        f"/message/search?q=alpha&room_id={private_room['id']}",
        headers=auth_headers(outsider["access_token"]),
    )
    assert unauthorized_scope.status_code == 403


def test_message_delete_removes_it_from_search(client):
    owner = register_user(client, "search-delete-owner")
    room = create_room(
        client,
        owner["access_token"],
        member_ids=[],
        name="search-delete-room",
    )
    message = create_message(
        client,
        owner["access_token"],
        room["id"],
        text="keyword-to-delete",
    )

    before_delete = client.get(
        "/message/search?q=keyword-to-delete",
        headers=auth_headers(owner["access_token"]),
    )
    assert before_delete.status_code == 200
    assert [item["id"] for item in before_delete.json()] == [message["id"]]

    delete_response = client.delete(
        f"/message/{message['id']}",
        headers=auth_headers(owner["access_token"]),
    )
    assert delete_response.status_code == 200

    after_delete = client.get(
        "/message/search?q=keyword-to-delete",
        headers=auth_headers(owner["access_token"]),
    )
    assert after_delete.status_code == 200
    assert after_delete.json() == []
