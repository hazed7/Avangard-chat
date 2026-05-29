from fastapi.testclient import TestClient

from tests.helpers.auth import auth_headers, register_user
from tests.helpers.chat import create_message, create_room


def test_user_profile_includes_social_stats(client: TestClient):
    alice = register_user(client, "profile_alice")
    bob = register_user(client, "profile_bob")
    charlie = register_user(client, "profile_charlie")

    prefs_resp = client.patch(
        "/user/me/preferences",
        headers=auth_headers(bob["access_token"]),
        json={"bio": "backend bio", "status_emoji": "🔥"},
    )
    assert prefs_resp.status_code == 200

    request_resp = client.post(
        f"/user/friends/request/{bob['user']['id']}",
        headers=auth_headers(alice["access_token"]),
    )
    assert request_resp.status_code == 200
    accept_resp = client.patch(
        f"/user/friends/request/{request_resp.json()['id']}?action=accept",
        headers=auth_headers(bob["access_token"]),
    )
    assert accept_resp.status_code == 200

    mutual_resp = client.post(
        f"/user/friends/request/{charlie['user']['id']}",
        headers=auth_headers(alice["access_token"]),
    )
    assert mutual_resp.status_code == 200
    mutual_accept_resp = client.patch(
        f"/user/friends/request/{mutual_resp.json()['id']}?action=accept",
        headers=auth_headers(charlie["access_token"]),
    )
    assert mutual_accept_resp.status_code == 200

    mutual_resp = client.post(
        f"/user/friends/request/{charlie['user']['id']}",
        headers=auth_headers(bob["access_token"]),
    )
    assert mutual_resp.status_code == 200
    mutual_accept_resp = client.patch(
        f"/user/friends/request/{mutual_resp.json()['id']}?action=accept",
        headers=auth_headers(charlie["access_token"]),
    )
    assert mutual_accept_resp.status_code == 200

    create_room(
        client,
        alice["access_token"],
        member_ids=[bob["user"]["id"], charlie["user"]["id"]],
        name="shared-group",
    )

    profile_resp = client.get(
        f"/user/{bob['user']['id']}/profile",
        headers=auth_headers(alice["access_token"]),
    )

    assert profile_resp.status_code == 200
    data = profile_resp.json()
    assert data["id"] == bob["user"]["id"]
    assert data["bio"] == "backend bio"
    assert data["status_emoji"] == "🔥"
    assert data["is_friend"] is True
    assert data["outgoing_friend_request_pending"] is False
    assert data["incoming_friend_request_pending"] is False
    assert data["friends_since"] is not None
    assert data["mutual_friends_count"] == 1
    assert data["shared_groups_count"] == 1


def test_friend_request_notifications_can_be_read_and_deleted(client: TestClient):
    alice = register_user(client, "notif_req_alice")
    bob = register_user(client, "notif_req_bob")

    send_resp = client.post(
        f"/user/friends/request/{bob['user']['id']}",
        headers=auth_headers(alice["access_token"]),
    )
    assert send_resp.status_code == 200

    list_resp = client.get(
        "/notifications",
        headers=auth_headers(bob["access_token"]),
    )
    assert list_resp.status_code == 200
    list_data = list_resp.json()
    assert list_data["unread_count"] == 1
    assert len(list_data["items"]) == 1
    notification_id = list_data["items"][0]["id"]
    assert list_data["items"][0]["category"] == "friend_request"
    assert list_data["items"][0]["is_read"] is False

    unread_resp = client.get(
        "/notifications/unread-count",
        headers=auth_headers(bob["access_token"]),
    )
    assert unread_resp.status_code == 200
    assert unread_resp.json()["unread_count"] == 1

    read_resp = client.post(
        f"/notifications/{notification_id}/read",
        headers=auth_headers(bob["access_token"]),
    )
    assert read_resp.status_code == 200
    assert read_resp.json()["is_read"] is True
    assert read_resp.json()["read_at"] is not None

    delete_resp = client.delete(
        f"/notifications/{notification_id}",
        headers=auth_headers(bob["access_token"]),
    )
    assert delete_resp.status_code == 200

    final_list_resp = client.get(
        "/notifications",
        headers=auth_headers(bob["access_token"]),
    )
    assert final_list_resp.status_code == 200
    assert final_list_resp.json()["items"] == []
    assert final_list_resp.json()["unread_count"] == 0


def test_accept_friend_request_creates_notification(client: TestClient):
    alice = register_user(client, "notif_accept_alice")
    bob = register_user(client, "notif_accept_bob")

    request_resp = client.post(
        f"/user/friends/request/{bob['user']['id']}",
        headers=auth_headers(alice["access_token"]),
    )
    assert request_resp.status_code == 200
    accept_resp = client.patch(
        f"/user/friends/request/{request_resp.json()['id']}?action=accept",
        headers=auth_headers(bob["access_token"]),
    )
    assert accept_resp.status_code == 200

    list_resp = client.get(
        "/notifications?category=friend_request_accepted",
        headers=auth_headers(alice["access_token"]),
    )
    assert list_resp.status_code == 200
    items = list_resp.json()["items"]
    assert len(items) == 1
    assert items[0]["category"] == "friend_request_accepted"


def test_notifications_read_all_and_unread_filter(client: TestClient):
    alice = register_user(client, "notif_read_all_alice")
    bob = register_user(client, "notif_read_all_bob")
    charlie = register_user(client, "notif_read_all_charlie")

    first_resp = client.post(
        f"/user/friends/request/{bob['user']['id']}",
        headers=auth_headers(alice["access_token"]),
    )
    assert first_resp.status_code == 200

    second_resp = client.post(
        f"/user/friends/request/{bob['user']['id']}",
        headers=auth_headers(charlie["access_token"]),
    )
    assert second_resp.status_code == 200

    unread_only_resp = client.get(
        "/notifications?unread_only=true",
        headers=auth_headers(bob["access_token"]),
    )
    assert unread_only_resp.status_code == 200
    assert len(unread_only_resp.json()["items"]) == 2
    assert unread_only_resp.json()["unread_count"] == 2

    read_all_resp = client.post(
        "/notifications/read-all",
        headers=auth_headers(bob["access_token"]),
    )
    assert read_all_resp.status_code == 200
    assert read_all_resp.json()["marked_count"] == 2

    final_unread_resp = client.get(
        "/notifications?unread_only=true",
        headers=auth_headers(bob["access_token"]),
    )
    assert final_unread_resp.status_code == 200
    assert final_unread_resp.json()["items"] == []
    assert final_unread_resp.json()["unread_count"] == 0


def test_group_invite_notification_respects_preferences(client: TestClient):
    owner = register_user(client, "notif_group_owner")
    member = register_user(client, "notif_group_member")

    prefs_resp = client.patch(
        "/user/me/preferences",
        headers=auth_headers(member["access_token"]),
        json={"notify_group_invites": False},
    )
    assert prefs_resp.status_code == 200

    room = create_room(
        client,
        owner["access_token"],
        member_ids=[],
        name="notif-group",
    )

    add_resp = client.post(
        f"/room/{room['id']}/members",
        headers=auth_headers(owner["access_token"]),
        json={"user_id": member["user"]["id"]},
    )
    assert add_resp.status_code == 200

    list_resp = client.get(
        "/notifications?category=group_invite",
        headers=auth_headers(member["access_token"]),
    )
    assert list_resp.status_code == 200
    assert list_resp.json()["items"] == []


def test_mention_notification_respects_preferences(client: TestClient):
    owner = register_user(client, "notif_mention_owner")
    member = register_user(client, "notif_mention_member")
    room = create_room(
        client,
        owner["access_token"],
        member_ids=[member["user"]["id"]],
        name="mention-room",
    )

    prefs_resp = client.patch(
        "/user/me/preferences",
        headers=auth_headers(member["access_token"]),
        json={"notify_mentions": False},
    )
    assert prefs_resp.status_code == 200

    create_message(
        client,
        owner["access_token"],
        room["id"],
        text=f"hello @{member['user']['username']}",
    )

    list_resp = client.get(
        "/notifications?category=mention",
        headers=auth_headers(member["access_token"]),
    )
    assert list_resp.status_code == 200
    assert list_resp.json()["items"] == []


def test_mention_notification_is_created_for_room_member(client: TestClient):
    owner = register_user(client, "notif_mention_on_owner")
    member = register_user(client, "notif_mention_on_member")
    outsider = register_user(client, "notif_mention_on_outsider")
    room = create_room(
        client,
        owner["access_token"],
        member_ids=[member["user"]["id"]],
        name="mention-room-on",
    )

    create_message(
        client,
        owner["access_token"],
        room["id"],
        text=(
            f"hello @{member['user']['username']} and @{outsider['user']['username']}"
        ),
    )

    member_list_resp = client.get(
        "/notifications?category=mention",
        headers=auth_headers(member["access_token"]),
    )
    assert member_list_resp.status_code == 200
    member_items = member_list_resp.json()["items"]
    assert len(member_items) == 1
    assert member_items[0]["payload"]["room_id"] == room["id"]

    outsider_list_resp = client.get(
        "/notifications?category=mention",
        headers=auth_headers(outsider["access_token"]),
    )
    assert outsider_list_resp.status_code == 200
    assert outsider_list_resp.json()["items"] == []


def test_mention_notification_skips_sender_even_if_they_mention_themself(
    client: TestClient,
):
    owner = register_user(client, "notif_self_owner")
    room = create_room(
        client,
        owner["access_token"],
        member_ids=[],
        name="mention-self-room",
    )

    create_message(
        client,
        owner["access_token"],
        room["id"],
        text=f"hello @{owner['user']['username']}",
    )

    list_resp = client.get(
        "/notifications?category=mention",
        headers=auth_headers(owner["access_token"]),
    )
    assert list_resp.status_code == 200
    assert list_resp.json()["items"] == []


def test_user_profile_reports_pending_and_block_state(client: TestClient):
    alice = register_user(client, "profile_pending_alice")
    bob = register_user(client, "profile_pending_bob")

    request_resp = client.post(
        f"/user/friends/request/{bob['user']['id']}",
        headers=auth_headers(alice["access_token"]),
    )
    assert request_resp.status_code == 200

    profile_resp = client.get(
        f"/user/{bob['user']['id']}/profile",
        headers=auth_headers(alice["access_token"]),
    )
    assert profile_resp.status_code == 200
    profile = profile_resp.json()
    assert profile["outgoing_friend_request_pending"] is True
    assert profile["incoming_friend_request_pending"] is False
    assert profile["outgoing_friend_request_id"] == request_resp.json()["id"]
    assert profile["incoming_friend_request_id"] is None
    assert profile["is_blocked_by_me"] is False
    assert profile["has_blocked_me"] is False

    block_resp = client.post(
        f"/user/blocks/{alice['user']['id']}",
        headers=auth_headers(bob["access_token"]),
    )
    assert block_resp.status_code == 200

    blocked_profile_resp = client.get(
        f"/user/{bob['user']['id']}/profile",
        headers=auth_headers(alice["access_token"]),
    )
    assert blocked_profile_resp.status_code == 200
    blocked_profile = blocked_profile_resp.json()
    assert blocked_profile["outgoing_friend_request_pending"] is False
    assert blocked_profile["outgoing_friend_request_id"] is None
    assert blocked_profile["has_blocked_me"] is True
