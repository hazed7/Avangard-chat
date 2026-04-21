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
