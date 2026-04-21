import asyncio

from app.modules.messages.model import Message
from tests.helpers.auth import auth_headers, register_user
from tests.helpers.chat import create_message, create_room


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


def test_message_search_supports_pagination(client):
    owner = register_user(client, "search-page-owner")
    room = create_room(
        client,
        owner["access_token"],
        member_ids=[],
        name="search-page-room",
    )

    first = create_message(
        client,
        owner["access_token"],
        room["id"],
        text="page-key one",
    )
    second = create_message(
        client,
        owner["access_token"],
        room["id"],
        text="page-key two",
    )

    first_page = client.get(
        "/message/search?q=page-key&limit=1&offset=0",
        headers=auth_headers(owner["access_token"]),
    )
    assert first_page.status_code == 200
    assert len(first_page.json()) == 1

    second_page = client.get(
        "/message/search?q=page-key&limit=1&offset=1",
        headers=auth_headers(owner["access_token"]),
    )
    assert second_page.status_code == 200
    assert len(second_page.json()) == 1
    assert first_page.json()[0]["id"] != second_page.json()[0]["id"]
    assert {first["id"], second["id"]} == {
        first_page.json()[0]["id"],
        second_page.json()[0]["id"],
    }


def test_message_search_room_scope_filters_results(client):
    owner = register_user(client, "search-scope-owner")
    room_a = create_room(
        client,
        owner["access_token"],
        member_ids=[],
        name="scope-room-a",
    )
    room_b = create_room(
        client,
        owner["access_token"],
        member_ids=[],
        name="scope-room-b",
    )

    message_a = create_message(
        client,
        owner["access_token"],
        room_a["id"],
        text="scope-key alpha",
    )
    create_message(
        client,
        owner["access_token"],
        room_b["id"],
        text="scope-key beta",
    )

    scoped = client.get(
        f"/message/search?q=scope-key&room_id={room_a['id']}",
        headers=auth_headers(owner["access_token"]),
    )
    assert scoped.status_code == 200
    assert [item["id"] for item in scoped.json()] == [message_a["id"]]
