from fastapi.testclient import TestClient

from tests.helpers.auth import auth_headers, register_user
from tests.helpers.chat import create_dm, create_message, create_room


def test_group_owner_can_add_and_remove_members_and_invalidate_access_cache(
    client: TestClient,
):
    owner = register_user(client, "group-owner")
    member = register_user(client, "group-member")

    room = create_room(
        client,
        owner["access_token"],
        member_ids=[],
        name="group-members-manage",
    )

    add_response = client.post(
        f"/room/{room['id']}/members",
        headers=auth_headers(owner["access_token"]),
        json={"user_id": member["user"]["id"]},
    )
    assert add_response.status_code == 200
    assert member["user"]["id"] in add_response.json()["member_ids"]

    member_room_response = client.get(
        f"/room/{room['id']}",
        headers=auth_headers(member["access_token"]),
    )
    assert member_room_response.status_code == 200

    remove_response = client.delete(
        f"/room/{room['id']}/members/{member['user']['id']}",
        headers=auth_headers(owner["access_token"]),
    )
    assert remove_response.status_code == 200
    assert member["user"]["id"] not in remove_response.json()["member_ids"]

    member_room_response_after = client.get(
        f"/room/{room['id']}",
        headers=auth_headers(member["access_token"]),
    )
    assert member_room_response_after.status_code == 403


def test_only_group_owner_can_manage_members(client: TestClient):
    owner = register_user(client, "group-owner-only")
    member = register_user(client, "group-existing-member")
    outsider = register_user(client, "group-outsider")

    room = create_room(
        client,
        owner["access_token"],
        member_ids=[member["user"]["id"]],
        name="group-owner-only-room",
    )

    add_response = client.post(
        f"/room/{room['id']}/members",
        headers=auth_headers(outsider["access_token"]),
        json={"user_id": outsider["user"]["id"]},
    )
    assert add_response.status_code == 403

    remove_response = client.delete(
        f"/room/{room['id']}/members/{member['user']['id']}",
        headers=auth_headers(outsider["access_token"]),
    )
    assert remove_response.status_code == 403


def test_group_member_management_rejects_dm_and_creator_removal(client: TestClient):
    owner = register_user(client, "membership-dm-owner")
    peer = register_user(client, "membership-dm-peer")
    extra = register_user(client, "membership-dm-extra")

    dm = create_dm(client, owner["access_token"], peer["user"]["id"])

    dm_add_response = client.post(
        f"/room/{dm['id']}/members",
        headers=auth_headers(owner["access_token"]),
        json={"user_id": extra["user"]["id"]},
    )
    assert dm_add_response.status_code == 400

    dm_remove_response = client.delete(
        f"/room/{dm['id']}/members/{peer['user']['id']}",
        headers=auth_headers(owner["access_token"]),
    )
    assert dm_remove_response.status_code == 400

    group = create_room(
        client,
        owner["access_token"],
        member_ids=[peer["user"]["id"]],
        name="creator-removal-room",
    )
    creator_remove_response = client.delete(
        f"/room/{group['id']}/members/{owner['user']['id']}",
        headers=auth_headers(owner["access_token"]),
    )
    assert creator_remove_response.status_code == 400


def test_group_member_management_handles_unknown_and_non_member_users(
    client: TestClient,
):
    owner = register_user(client, "membership-unknown-owner")
    member = register_user(client, "membership-unknown-member")
    non_member = register_user(client, "membership-unknown-non-member")

    room = create_room(
        client,
        owner["access_token"],
        member_ids=[member["user"]["id"]],
        name="membership-unknown-room",
    )

    remove_non_member = client.delete(
        f"/room/{room['id']}/members/{non_member['user']['id']}",
        headers=auth_headers(owner["access_token"]),
    )
    assert remove_non_member.status_code == 200
    assert member["user"]["id"] in remove_non_member.json()["member_ids"]

    unknown_id = "00000000-0000-0000-0000-000000000000"
    add_unknown = client.post(
        f"/room/{room['id']}/members",
        headers=auth_headers(owner["access_token"]),
        json={"user_id": unknown_id},
    )
    assert add_unknown.status_code == 400

    remove_unknown = client.delete(
        f"/room/{room['id']}/members/{unknown_id}",
        headers=auth_headers(owner["access_token"]),
    )
    assert remove_unknown.status_code == 400


def test_message_read_state_and_unread_counts(client: TestClient):
    owner = register_user(client, "read-owner")
    member = register_user(client, "read-member")

    room = create_room(
        client,
        owner["access_token"],
        member_ids=[member["user"]["id"]],
        name="read-room",
    )

    first = create_message(
        client,
        owner["access_token"],
        room["id"],
        text="first unread",
    )
    second = create_message(
        client,
        owner["access_token"],
        room["id"],
        text="second unread",
    )

    assert owner["user"]["id"] in first["read_by"]
    assert owner["user"]["id"] in second["read_by"]

    member_unread = client.get(
        "/message/unread",
        headers=auth_headers(member["access_token"]),
    )
    assert member_unread.status_code == 200
    assert member_unread.json()["total"] == 2
    assert member_unread.json()["by_room"] == [
        {"room_id": room["id"], "unread_count": 2}
    ]

    first_read_response = client.post(
        f"/message/{first['id']}/read",
        headers=auth_headers(member["access_token"]),
    )
    assert first_read_response.status_code == 200
    assert set(first_read_response.json()["read_by"]) == {
        owner["user"]["id"],
        member["user"]["id"],
    }

    room_unread_after_one_read = client.get(
        f"/message/unread?room_id={room['id']}",
        headers=auth_headers(member["access_token"]),
    )
    assert room_unread_after_one_read.status_code == 200
    assert room_unread_after_one_read.json() == {
        "total": 1,
        "by_room": [{"room_id": room["id"], "unread_count": 1}],
    }

    mark_room_read_response = client.post(
        f"/message/room/{room['id']}/read",
        headers=auth_headers(member["access_token"]),
    )
    assert mark_room_read_response.status_code == 200
    assert mark_room_read_response.json() == {"ok": True, "marked_count": 1}

    member_unread_after_all_read = client.get(
        "/message/unread",
        headers=auth_headers(member["access_token"]),
    )
    assert member_unread_after_all_read.status_code == 200
    assert member_unread_after_all_read.json() == {"total": 0, "by_room": []}

    room_scoped_after_all_read = client.get(
        f"/message/unread?room_id={room['id']}",
        headers=auth_headers(member["access_token"]),
    )
    assert room_scoped_after_all_read.status_code == 200
    assert room_scoped_after_all_read.json() == {
        "total": 0,
        "by_room": [{"room_id": room["id"], "unread_count": 0}],
    }

    owner_unread = client.get(
        "/message/unread",
        headers=auth_headers(owner["access_token"]),
    )
    assert owner_unread.status_code == 200
    assert owner_unread.json() == {"total": 0, "by_room": []}


def test_read_state_requires_room_access(client: TestClient):
    owner = register_user(client, "read-access-owner")
    member = register_user(client, "read-access-member")
    outsider = register_user(client, "read-access-outsider")

    room = create_room(
        client,
        owner["access_token"],
        member_ids=[member["user"]["id"]],
        name="read-access-room",
    )
    message = create_message(
        client,
        owner["access_token"],
        room["id"],
        text="private",
    )

    outsider_mark_message = client.post(
        f"/message/{message['id']}/read",
        headers=auth_headers(outsider["access_token"]),
    )
    assert outsider_mark_message.status_code == 403

    outsider_mark_room = client.post(
        f"/message/room/{room['id']}/read",
        headers=auth_headers(outsider["access_token"]),
    )
    assert outsider_mark_room.status_code == 403

    outsider_room_unread = client.get(
        f"/message/unread?room_id={room['id']}",
        headers=auth_headers(outsider["access_token"]),
    )
    assert outsider_room_unread.status_code == 403


def test_new_group_member_gets_unread_counter_seeded_from_history(client: TestClient):
    owner = register_user(client, "seed-owner")
    member = register_user(client, "seed-member")

    room = create_room(
        client,
        owner["access_token"],
        member_ids=[],
        name="seed-room",
    )
    create_message(
        client,
        owner["access_token"],
        room["id"],
        text="seed one",
    )
    create_message(
        client,
        owner["access_token"],
        room["id"],
        text="seed two",
    )

    add_member = client.post(
        f"/room/{room['id']}/members",
        headers=auth_headers(owner["access_token"]),
        json={"user_id": member["user"]["id"]},
    )
    assert add_member.status_code == 200

    member_unread = client.get(
        f"/message/unread?room_id={room['id']}",
        headers=auth_headers(member["access_token"]),
    )
    assert member_unread.status_code == 200
    assert member_unread.json() == {
        "total": 2,
        "by_room": [{"room_id": room["id"], "unread_count": 2}],
    }
