import asyncio
import base64
import json
import time

import pytest

from app.modules.messages.model import Message
from app.modules.messages.unread.service import UnreadCounterService
from app.modules.system import dependencies
from app.modules.system.cleanup_jobs.model import CleanupJob
from app.platform.config.settings import settings
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


def test_message_search_rate_limit_returns_429(
    client,
    monkeypatch,
):
    owner = register_user(client, "search-rate-limit-owner")
    monkeypatch.setattr(settings, "message_search_rate_limit_max_attempts", 1)
    monkeypatch.setattr(settings, "message_search_rate_limit_window_seconds", 60)

    first = client.get(
        "/message/search?q=rate-limit-check",
        headers=auth_headers(owner["access_token"]),
    )
    assert first.status_code == 200

    second = client.get(
        "/message/search?q=rate-limit-check",
        headers=auth_headers(owner["access_token"]),
    )
    assert second.status_code == 429


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


def test_message_cursors_are_opaque_and_not_plain_json(client):
    owner = register_user(client, "opaque-cursor-owner")
    room = create_room(
        client,
        owner["access_token"],
        member_ids=[],
        name="opaque-cursor-room",
    )
    first = create_message(
        client,
        owner["access_token"],
        room["id"],
        text="opaque cursor one",
    )
    create_message(
        client,
        owner["access_token"],
        room["id"],
        text="opaque cursor two",
    )

    history_page = client.get(
        f"/message/room/{room['id']}?limit=1",
        headers=auth_headers(owner["access_token"]),
    )
    assert history_page.status_code == 200
    history_cursor = history_page.json()["next_cursor"]
    assert history_cursor is not None

    history_decoded = base64.urlsafe_b64decode(history_cursor.encode())
    with pytest.raises((UnicodeDecodeError, json.JSONDecodeError)):
        json.loads(history_decoded.decode())
    assert first["id"].encode() not in history_decoded

    search_page = client.get(
        "/message/search?q=opaque&limit=1",
        headers=auth_headers(owner["access_token"]),
    )
    assert search_page.status_code == 200
    search_cursor = search_page.json()["next_cursor"]
    assert search_cursor is not None

    search_decoded = base64.urlsafe_b64decode(search_cursor.encode())
    with pytest.raises((UnicodeDecodeError, json.JSONDecodeError)):
        json.loads(search_decoded.decode())


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


def test_send_rolls_back_message_and_search_doc_when_unread_increment_fails(
    client,
    monkeypatch,
):
    owner = register_user(client, "send-rollback-owner")
    room = create_room(
        client,
        owner["access_token"],
        member_ids=[],
        name="send-rollback-room",
    )
    fake_typesense = dependencies.get_typesense_service_singleton()

    async def fail_increment_for_new_message(self, *, room, sender_id):  # noqa: ANN001
        raise RuntimeError("unread increment failed")

    monkeypatch.setattr(
        UnreadCounterService,
        "increment_for_new_message",
        fail_increment_for_new_message,
    )

    with pytest.raises(RuntimeError, match="unread increment failed"):
        client.post(
            "/message",
            headers=auth_headers(owner["access_token"]),
            json={"room_id": room["id"], "text": "rollback-search-cleanup"},
        )
    assert asyncio.run(Message.find({}).to_list()) == []
    assert fake_typesense._docs == {}


def test_edit_rolls_back_db_and_search_doc_on_index_runtime_failure(
    client,
    monkeypatch,
):
    owner = register_user(client, "edit-rollback-owner")
    room = create_room(
        client,
        owner["access_token"],
        member_ids=[],
        name="edit-rollback-room",
    )
    message = create_message(
        client,
        owner["access_token"],
        room["id"],
        text="before-edit-text",
    )
    fake_typesense = dependencies.get_typesense_service_singleton()
    original_upsert = fake_typesense.upsert_message
    upsert_calls = {"count": 0}

    async def fail_first_upsert(  # noqa: ANN001
        *,
        message_id,
        room_id,
        sender_id,
        text,
        created_at,
        is_deleted,
    ):
        upsert_calls["count"] += 1
        if upsert_calls["count"] == 1:
            raise RuntimeError("typesense write failed")
        await original_upsert(
            message_id=message_id,
            room_id=room_id,
            sender_id=sender_id,
            text=text,
            created_at=created_at,
            is_deleted=is_deleted,
        )

    monkeypatch.setattr(fake_typesense, "upsert_message", fail_first_upsert)

    with pytest.raises(RuntimeError, match="typesense write failed"):
        client.patch(
            f"/message/{message['id']}",
            headers=auth_headers(owner["access_token"]),
            json={"text": "after-edit-text"},
        )

    history_response = client.get(
        f"/message/room/{room['id']}",
        headers=auth_headers(owner["access_token"]),
    )
    assert history_response.status_code == 200
    history_item = history_response.json()["items"][0]
    assert history_item["text"] == "before-edit-text"
    assert history_item["is_edited"] is False
    assert fake_typesense._docs[message["id"]]["text"] == "before-edit-text"


def test_edit_failure_is_not_silent_when_rollback_save_fails(client, monkeypatch):
    owner = register_user(client, "edit-rollback-save-owner")
    room = create_room(
        client,
        owner["access_token"],
        member_ids=[],
        name="edit-rollback-save-room",
    )
    message = create_message(
        client,
        owner["access_token"],
        room["id"],
        text="rollback-save-before",
    )
    fake_typesense = dependencies.get_typesense_service_singleton()

    async def fail_upsert(
        *, message_id, room_id, sender_id, text, created_at, is_deleted
    ):  # noqa: ANN001,E501
        raise RuntimeError("typesense write failed")

    monkeypatch.setattr(fake_typesense, "upsert_message", fail_upsert)

    original_save = Message.save
    save_calls = {"count": 0}

    async def fail_second_save(self, *args, **kwargs):  # noqa: ANN002, ANN003
        save_calls["count"] += 1
        if save_calls["count"] == 2:
            raise RuntimeError("rollback save failed")
        return await original_save(self, *args, **kwargs)

    monkeypatch.setattr(Message, "save", fail_second_save)

    with pytest.raises(RuntimeError, match="rollback save failed"):
        client.patch(
            f"/message/{message['id']}",
            headers=auth_headers(owner["access_token"]),
            json={"text": "rollback-save-after"},
        )
