import asyncio
import time

from app.modules.messages.model import Message
from app.modules.system.cleanup_jobs.model import CleanupJob
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
    owner_result_ids = [message["id"] for message in owner_search.json()["items"]]
    assert private_message["id"] in owner_result_ids

    outsider_search = client.get(
        "/message/search?q=alpha",
        headers=auth_headers(outsider["access_token"]),
    )
    assert outsider_search.status_code == 200
    outsider_result_ids = [message["id"] for message in outsider_search.json()["items"]]
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
    assert [item["id"] for item in before_delete.json()["items"]] == [message["id"]]

    delete_response = client.delete(
        f"/message/{message['id']}",
        headers=auth_headers(owner["access_token"]),
    )
    assert delete_response.status_code == 200

    after_delete_payload = None
    for _ in range(30):
        after_delete = client.get(
            "/message/search?q=keyword-to-delete",
            headers=auth_headers(owner["access_token"]),
        )
        assert after_delete.status_code == 200
        after_delete_payload = after_delete.json()
        if after_delete_payload == {"items": [], "next_cursor": None}:
            break
        time.sleep(0.05)
    assert after_delete_payload == {"items": [], "next_cursor": None}


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
        "/message/search?q=page-key&limit=1",
        headers=auth_headers(owner["access_token"]),
    )
    assert first_page.status_code == 200
    first_payload = first_page.json()
    assert len(first_payload["items"]) == 1
    assert first_payload["next_cursor"] is not None

    second_page = client.get(
        f"/message/search?q=page-key&limit=1&cursor={first_payload['next_cursor']}",
        headers=auth_headers(owner["access_token"]),
    )
    assert second_page.status_code == 200
    second_payload = second_page.json()
    assert len(second_payload["items"]) == 1
    assert first_payload["items"][0]["id"] != second_payload["items"][0]["id"]
    assert {first["id"], second["id"]} == {
        first_payload["items"][0]["id"],
        second_payload["items"][0]["id"],
    }


def test_message_search_does_not_use_per_id_message_get(
    client,
    monkeypatch,
):
    owner = register_user(client, "search-bulk-owner")
    room = create_room(
        client,
        owner["access_token"],
        member_ids=[],
        name="search-bulk-room",
    )
    create_message(
        client,
        owner["access_token"],
        room["id"],
        text="bulk-search-keyword",
    )

    async def fail_message_get(*args, **kwargs):  # noqa: ANN002, ANN003
        raise AssertionError("Message.get must not be called during search")

    monkeypatch.setattr(Message, "get", fail_message_get)

    response = client.get(
        "/message/search?q=bulk-search-keyword",
        headers=auth_headers(owner["access_token"]),
    )
    assert response.status_code == 200
    assert len(response.json()["items"]) == 1


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
    assert [item["id"] for item in scoped.json()["items"]] == [message_a["id"]]


def test_deleted_message_is_redacted_in_history(client):
    owner = register_user(client, "history-redact-owner")
    room = create_room(
        client,
        owner["access_token"],
        member_ids=[],
        name="history-redact-room",
    )
    message = create_message(
        client,
        owner["access_token"],
        room["id"],
        text="must be hidden after delete",
    )

    delete_response = client.delete(
        f"/message/{message['id']}",
        headers=auth_headers(owner["access_token"]),
    )
    assert delete_response.status_code == 200

    history_response = client.get(
        f"/message/room/{room['id']}",
        headers=auth_headers(owner["access_token"]),
    )
    assert history_response.status_code == 200
    item = history_response.json()["items"][0]
    assert item["is_deleted"] is True
    assert item["text"] == "[deleted]"


def test_message_cursor_rejects_invalid_values(client):
    owner = register_user(client, "invalid-cursor-owner")
    room = create_room(
        client,
        owner["access_token"],
        member_ids=[],
        name="invalid-cursor-room",
    )
    create_message(
        client,
        owner["access_token"],
        room["id"],
        text="cursor sample",
    )

    invalid_history_cursor = client.get(
        f"/message/room/{room['id']}?cursor=invalid",
        headers=auth_headers(owner["access_token"]),
    )
    assert invalid_history_cursor.status_code == 400

    invalid_search_cursor = client.get(
        "/message/search?q=cursor&cursor=invalid",
        headers=auth_headers(owner["access_token"]),
    )
    assert invalid_search_cursor.status_code == 400


def test_room_delete_cascades_messages_and_search_docs(client):
    owner = register_user(client, "cascade-owner")
    room = create_room(
        client,
        owner["access_token"],
        member_ids=[],
        name="cascade-room",
    )
    message = create_message(
        client,
        owner["access_token"],
        room["id"],
        text="cascade keyword",
    )

    delete_room_response = client.delete(
        f"/room/{room['id']}",
        headers=auth_headers(owner["access_token"]),
    )
    assert delete_room_response.status_code == 200

    message_doc = asyncio.run(Message.get(message["id"]))
    assert message_doc is None

    room_search = client.get(
        f"/message/search?q=cascade&room_id={room['id']}",
        headers=auth_headers(owner["access_token"]),
    )
    assert room_search.status_code == 404


def test_delete_operations_enqueue_cleanup_jobs(client):
    owner = register_user(client, "cleanup-job-owner")
    room = create_room(
        client,
        owner["access_token"],
        member_ids=[],
        name="cleanup-job-room",
    )
    message = create_message(
        client,
        owner["access_token"],
        room["id"],
        text="cleanup enqueue",
    )

    delete_message_response = client.delete(
        f"/message/{message['id']}",
        headers=auth_headers(owner["access_token"]),
    )
    assert delete_message_response.status_code == 200

    message_job = asyncio.run(
        CleanupJob.get_motor_collection().find_one(
            {
                "job_type": "message_delete_cleanup",
                "payload.message_id": message["id"],
            }
        )
    )
    assert message_job is not None

    delete_room_response = client.delete(
        f"/room/{room['id']}",
        headers=auth_headers(owner["access_token"]),
    )
    assert delete_room_response.status_code == 200

    room_job = asyncio.run(
        CleanupJob.get_motor_collection().find_one(
            {"job_type": "room_delete_cleanup", "payload.room_id": room["id"]}
        )
    )
    assert room_job is not None
