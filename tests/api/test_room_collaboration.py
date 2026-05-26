import io

from fastapi.testclient import TestClient

from tests.helpers.auth import auth_headers, register_user
from tests.helpers.chat import create_message, create_room

PNG_1X1 = (
    b"\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR\x00\x00\x00\x01\x00\x00\x00\x01"
    b"\x08\x06\x00\x00\x00\x1f\x15\xc4\x89\x00\x00\x00\rIDATx\x9cc````\x00"
    b"\x00\x00\x05\x00\x01\xa5\xf6E@\x00\x00\x00\x00IEND\xaeB`\x82"
)


def test_owner_can_promote_admin_and_admin_can_manage_group_settings(
    client: TestClient,
):
    owner = register_user(client, "collab-owner")
    admin_candidate = register_user(client, "collab-admin")
    room = create_room(
        client,
        owner["access_token"],
        member_ids=[admin_candidate["user"]["id"]],
        name="original-group",
    )

    promote_response = client.post(
        f"/room/{room['id']}/admins",
        headers=auth_headers(owner["access_token"]),
        json={"user_id": admin_candidate["user"]["id"]},
    )
    assert promote_response.status_code == 200
    assert admin_candidate["user"]["id"] in promote_response.json()["admin_ids"]

    rename_response = client.patch(
        f"/room/{room['id']}",
        headers=auth_headers(admin_candidate["access_token"]),
        json={"name": "renamed-group"},
    )
    assert rename_response.status_code == 200
    assert rename_response.json()["name"] == "renamed-group"

    avatar_response = client.post(
        f"/room/{room['id']}/avatar",
        headers=auth_headers(admin_candidate["access_token"]),
        files={"file": ("avatar.png", io.BytesIO(PNG_1X1), "image/png")},
    )
    assert avatar_response.status_code == 200
    assert avatar_response.json()["avatar_object_path"] is not None


def test_non_admin_cannot_update_group_settings_or_invite(client: TestClient):
    owner = register_user(client, "collab-owner-2")
    member = register_user(client, "collab-member-2")
    room = create_room(
        client,
        owner["access_token"],
        member_ids=[member["user"]["id"]],
        name="locked-group",
    )

    rename_response = client.patch(
        f"/room/{room['id']}",
        headers=auth_headers(member["access_token"]),
        json={"name": "nope"},
    )
    assert rename_response.status_code == 403

    invite_response = client.post(
        f"/room/{room['id']}/invite-link",
        headers=auth_headers(member["access_token"]),
    )
    assert invite_response.status_code == 403


def test_admin_can_create_invite_and_user_can_join_by_token(client: TestClient):
    owner = register_user(client, "invite-owner")
    admin = register_user(client, "invite-admin")
    joiner = register_user(client, "invite-joiner")
    room = create_room(
        client,
        owner["access_token"],
        member_ids=[admin["user"]["id"]],
        name="invite-group",
    )

    promote_response = client.post(
        f"/room/{room['id']}/admins",
        headers=auth_headers(owner["access_token"]),
        json={"user_id": admin["user"]["id"]},
    )
    assert promote_response.status_code == 200

    invite_response = client.post(
        f"/room/{room['id']}/invite-link",
        headers=auth_headers(admin["access_token"]),
    )
    assert invite_response.status_code == 200
    token = invite_response.json()["token"]

    join_response = client.post(
        f"/room/join/{token}",
        headers=auth_headers(joiner["access_token"]),
    )
    assert join_response.status_code == 200
    assert joiner["user"]["id"] in join_response.json()["member_ids"]


def test_room_preferences_support_archive_and_mute(client: TestClient):
    owner = register_user(client, "pref-owner")
    room = create_room(client, owner["access_token"], member_ids=[], name="pref-group")

    pref_response = client.patch(
        f"/room/{room['id']}/preferences",
        headers=auth_headers(owner["access_token"]),
        json={"mute_forever": True, "is_archived": True},
    )
    assert pref_response.status_code == 200
    assert pref_response.json()["mute_forever"] is True
    assert pref_response.json()["is_archived"] is True

    rooms_response = client.get(
        f"/room/user/{owner['user']['id']}",
        headers=auth_headers(owner["access_token"]),
    )
    assert rooms_response.status_code == 200
    payload = rooms_response.json()
    assert payload["groups"] == []
    assert len(payload["archived"]) == 1
    assert payload["archived"][0]["id"] == room["id"]


def test_pins_are_newest_first_capped_and_auto_unpinned_on_delete(client: TestClient):
    owner = register_user(client, "pin-owner")
    member = register_user(client, "pin-member")
    room = create_room(
        client,
        owner["access_token"],
        member_ids=[member["user"]["id"]],
        name="pin-group",
    )

    message_ids = []
    for index in range(21):
        message = create_message(
            client,
            owner["access_token"],
            room["id"],
            text=f"message {index}",
        )
        message_ids.append(message["id"])
        pin_response = client.post(
            f"/room/{room['id']}/pins/{message['id']}",
            headers=auth_headers(member["access_token"]),
        )
        assert pin_response.status_code == 200

    list_response = client.get(
        f"/room/{room['id']}/pins",
        headers=auth_headers(owner["access_token"]),
    )
    assert list_response.status_code == 200
    pins = list_response.json()
    assert len(pins) == 20
    assert pins[0]["message"]["id"] == message_ids[-1]
    assert pins[-1]["message"]["id"] == message_ids[1]

    delete_response = client.delete(
        f"/message/{message_ids[-1]}",
        headers=auth_headers(owner["access_token"]),
    )
    assert delete_response.status_code == 200

    after_delete_response = client.get(
        f"/room/{room['id']}/pins",
        headers=auth_headers(owner["access_token"]),
    )
    assert after_delete_response.status_code == 200
    remaining_ids = [item["message"]["id"] for item in after_delete_response.json()]
    assert message_ids[-1] not in remaining_ids


def test_mentions_and_reactions_are_persisted_on_messages(client: TestClient):
    owner = register_user(client, "mention-owner")
    bob = register_user(client, "mention-bob")
    charlie = register_user(client, "mention-charlie")
    room = create_room(
        client,
        owner["access_token"],
        member_ids=[bob["user"]["id"], charlie["user"]["id"]],
        name="mention-group",
    )

    message = create_message(
        client,
        owner["access_token"],
        room["id"],
        text=f"hi @{bob['user']['username']} and @{charlie['user']['username']}",
    )
    assert set(message["mentioned_user_ids"]) == {
        bob["user"]["id"],
        charlie["user"]["id"],
    }
    assert message["reactions"] == []

    first_reaction = client.post(
        f"/message/{message['id']}/reaction",
        headers=auth_headers(bob["access_token"]),
        json={"emoji": "🔥"},
    )
    assert first_reaction.status_code == 200
    assert first_reaction.json()["reactions"] == [
        {"emoji": "🔥", "user_ids": [bob["user"]["id"]], "count": 1}
    ]

    replace_reaction = client.post(
        f"/message/{message['id']}/reaction",
        headers=auth_headers(bob["access_token"]),
        json={"emoji": "👍"},
    )
    assert replace_reaction.status_code == 200
    assert replace_reaction.json()["reactions"] == [
        {"emoji": "👍", "user_ids": [bob["user"]["id"]], "count": 1}
    ]

    toggle_off = client.post(
        f"/message/{message['id']}/reaction",
        headers=auth_headers(bob["access_token"]),
        json={"emoji": "👍"},
    )
    assert toggle_off.status_code == 200
    assert toggle_off.json()["reactions"] == []
