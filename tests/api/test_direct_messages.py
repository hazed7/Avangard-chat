from fastapi.testclient import TestClient

from tests.helpers.auth import auth_headers, register_user
from tests.helpers.chat import create_dm, create_room


def test_dm_endpoint_creates_or_reuses_same_room(client: TestClient):
    alice = register_user(client, "dm-alice")
    bob = register_user(client, "dm-bob")

    first_dm = create_dm(client, alice["access_token"], bob["user"]["id"])
    assert first_dm["is_group"] is False
    assert set(first_dm["member_ids"]) == {
        alice["user"]["id"],
        bob["user"]["id"],
    }

    second_dm = create_dm(client, alice["access_token"], bob["user"]["id"])
    assert second_dm["id"] == first_dm["id"]

    reverse_dm = create_dm(client, bob["access_token"], alice["user"]["id"])
    assert reverse_dm["id"] == first_dm["id"]


def test_dm_endpoint_rejects_self_dm(client: TestClient):
    alice = register_user(client, "dm-self")

    response = client.post(
        "/room/dm",
        headers=auth_headers(alice["access_token"]),
        json={"user_id": alice["user"]["id"]},
    )

    assert response.status_code == 400
    assert (
        response.json()["detail"] == "Cannot create a direct message room with yourself"
    )


def test_group_create_rejects_legacy_is_group_field(client: TestClient):
    alice = register_user(client, "legacy-group")

    response = client.post(
        "/room/group",
        headers=auth_headers(alice["access_token"]),
        json={"name": "legacy", "member_ids": [], "is_group": True},
    )

    assert response.status_code == 422


def test_room_list_is_partitioned_by_room_type(client: TestClient):
    alice = register_user(client, "partition-alice")
    bob = register_user(client, "partition-bob")
    charlie = register_user(client, "partition-charlie")

    create_room(
        client,
        alice["access_token"],
        member_ids=[bob["user"]["id"]],
        name="group-room",
    )
    dm = create_dm(client, alice["access_token"], charlie["user"]["id"])

    response = client.get(
        f"/room/user/{alice['user']['id']}",
        headers=auth_headers(alice["access_token"]),
    )

    assert response.status_code == 200
    payload = response.json()
    assert len(payload["groups"]) == 1
    assert len(payload["dms"]) == 1
    assert payload["dms"][0]["id"] == dm["id"]
    assert payload["next_cursor"] is None


def test_room_list_supports_cursor_pagination(client: TestClient):
    alice = register_user(client, "rooms-page-alice")

    first_group = create_room(
        client,
        alice["access_token"],
        member_ids=[],
        name="page-group-1",
    )
    second_group = create_room(
        client,
        alice["access_token"],
        member_ids=[],
        name="page-group-2",
    )

    first_page = client.get(
        f"/room/user/{alice['user']['id']}?limit=1",
        headers=auth_headers(alice["access_token"]),
    )
    assert first_page.status_code == 200
    first_payload = first_page.json()
    assert first_payload["next_cursor"] is not None
    assert len(first_payload["groups"]) == 1
    first_id = first_payload["groups"][0]["id"]

    second_page = client.get(
        (
            f"/room/user/{alice['user']['id']}?limit=1"
            f"&cursor={first_payload['next_cursor']}"
        ),
        headers=auth_headers(alice["access_token"]),
    )
    assert second_page.status_code == 200
    second_payload = second_page.json()
    assert len(second_payload["groups"]) == 1
    second_id = second_payload["groups"][0]["id"]
    assert first_id != second_id
    assert {first_id, second_id} == {first_group["id"], second_group["id"]}
