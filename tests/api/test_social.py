from fastapi.testclient import TestClient

from tests.helpers.auth import auth_headers, register_user
from tests.helpers.chat import create_room


def test_preferences_defaults(client: TestClient):
    """New user has default privacy settings"""
    user = register_user(client, "pref_test")
    resp = client.get(
        "/user/me/preferences", headers=auth_headers(user["access_token"])
    )
    assert resp.status_code == 200
    data = resp.json()
    assert data["privacy_messaging"] == "everyone"
    assert data["privacy_group_invite"] == "everyone"
    assert data["privacy_calling"] == "everyone"
    assert data["bio"] is None
    assert data["status_emoji"] is None


def test_update_preferences(client: TestClient):
    """User can update their preferences"""
    user = register_user(client, "pref_update")
    resp = client.patch(
        "/user/me/preferences",
        headers=auth_headers(user["access_token"]),
        json={"bio": "hello world", "privacy_messaging": "friends_only"},
    )
    assert resp.status_code == 200
    data = resp.json()
    assert data["bio"] == "hello world"
    assert data["privacy_messaging"] == "friends_only"


def test_update_preferences_can_clear_profile_fields(client: TestClient):
    user = register_user(client, "pref_clear")
    set_resp = client.patch(
        "/user/me/preferences",
        headers=auth_headers(user["access_token"]),
        json={"bio": "filled", "status_emoji": "🔥"},
    )
    assert set_resp.status_code == 200

    clear_resp = client.patch(
        "/user/me/preferences",
        headers=auth_headers(user["access_token"]),
        json={"bio": "", "status_emoji": ""},
    )
    assert clear_resp.status_code == 200
    data = clear_resp.json()
    assert data["bio"] is None
    assert data["status_emoji"] is None


def test_update_preferences_rejects_invalid_privacy_value(client: TestClient):
    user = register_user(client, "pref_invalid")
    resp = client.patch(
        "/user/me/preferences",
        headers=auth_headers(user["access_token"]),
        json={"privacy_calling": "nobody"},
    )
    assert resp.status_code == 422


def test_send_friend_request(client: TestClient):
    """User can send a friend request"""
    alice = register_user(client, "friend_alice")
    bob = register_user(client, "friend_bob")
    resp = client.post(
        f"/user/friends/request/{bob['user']['id']}",
        headers=auth_headers(alice["access_token"]),
    )
    assert resp.status_code == 200
    data = resp.json()
    assert data["status"] == "pending"
    assert data["from_user_id"] == alice["user"]["id"]
    assert data["to_user_id"] == bob["user"]["id"]


def test_accept_friend_request(client: TestClient):
    """User can accept a friend request"""
    alice = register_user(client, "accept_alice")
    bob = register_user(client, "accept_bob")
    req_resp = client.post(
        f"/user/friends/request/{bob['user']['id']}",
        headers=auth_headers(alice["access_token"]),
    )
    request_id = req_resp.json()["id"]
    resp = client.patch(
        f"/user/friends/request/{request_id}?action=accept",
        headers=auth_headers(bob["access_token"]),
    )
    assert resp.status_code == 200
    assert resp.json()["status"] == "accepted"


def test_reject_friend_request(client: TestClient):
    """User can reject a friend request"""
    alice = register_user(client, "reject_alice")
    bob = register_user(client, "reject_bob")
    req_resp = client.post(
        f"/user/friends/request/{bob['user']['id']}",
        headers=auth_headers(alice["access_token"]),
    )
    request_id = req_resp.json()["id"]
    resp = client.patch(
        f"/user/friends/request/{request_id}?action=reject",
        headers=auth_headers(bob["access_token"]),
    )
    assert resp.status_code == 200
    assert resp.json()["status"] == "rejected"


def test_list_pending_friend_requests_includes_incoming_and_outgoing(
    client: TestClient,
):
    alice = register_user(client, "pending_alice")
    bob = register_user(client, "pending_bob")
    charlie = register_user(client, "pending_charlie")

    outgoing = client.post(
        f"/user/friends/request/{bob['user']['id']}",
        headers=auth_headers(alice["access_token"]),
    )
    assert outgoing.status_code == 200

    incoming = client.post(
        f"/user/friends/request/{alice['user']['id']}",
        headers=auth_headers(charlie["access_token"]),
    )
    assert incoming.status_code == 200

    resp = client.get(
        "/user/me/friends/requests",
        headers=auth_headers(alice["access_token"]),
    )

    assert resp.status_code == 200
    requests = resp.json()
    assert {item["id"] for item in requests} == {
        outgoing.json()["id"],
        incoming.json()["id"],
    }


def test_list_friends(client: TestClient):
    """User can list their friends"""
    alice = register_user(client, "listf_alice")
    bob = register_user(client, "listf_bob")
    req_resp = client.post(
        f"/user/friends/request/{bob['user']['id']}",
        headers=auth_headers(alice["access_token"]),
    )
    client.patch(
        f"/user/friends/request/{req_resp.json()['id']}?action=accept",
        headers=auth_headers(bob["access_token"]),
    )
    resp = client.get("/user/me/friends", headers=auth_headers(alice["access_token"]))
    assert resp.status_code == 200
    friends = resp.json()
    assert len(friends) == 1
    assert friends[0]["user_id"] == bob["user"]["id"]
    assert friends[0]["is_online"] is False
    assert friends[0]["since"]


def test_remove_friend(client: TestClient):
    """User can remove a friend"""
    alice = register_user(client, "remf_alice")
    bob = register_user(client, "remf_bob")
    req_resp = client.post(
        f"/user/friends/request/{bob['user']['id']}",
        headers=auth_headers(alice["access_token"]),
    )
    client.patch(
        f"/user/friends/request/{req_resp.json()['id']}?action=accept",
        headers=auth_headers(bob["access_token"]),
    )
    resp = client.delete(
        f"/user/friends/{bob['user']['id']}",
        headers=auth_headers(alice["access_token"]),
    )
    assert resp.status_code == 204
    # Verify not friends anymore
    friends_resp = client.get(
        "/user/me/friends", headers=auth_headers(alice["access_token"])
    )
    assert len(friends_resp.json()) == 0


def test_remove_missing_friend_returns_404(client: TestClient):
    alice = register_user(client, "rem_missing_alice")
    bob = register_user(client, "rem_missing_bob")

    resp = client.delete(
        f"/user/friends/{bob['user']['id']}",
        headers=auth_headers(alice["access_token"]),
    )

    assert resp.status_code == 404


def test_block_user(client: TestClient):
    """User can block another user"""
    alice = register_user(client, "block_alice")
    bob = register_user(client, "block_bob")
    resp = client.post(
        f"/user/blocks/{bob['user']['id']}",
        headers=auth_headers(alice["access_token"]),
    )
    assert resp.status_code == 200
    data = resp.json()
    assert data["user_id"] == bob["user"]["id"]
    assert data["username"] == bob["user"]["username"]
    assert data["blocked_at"]


def test_block_user_rejects_duplicate_block(client: TestClient):
    alice = register_user(client, "blockdup_alice")
    bob = register_user(client, "blockdup_bob")

    first = client.post(
        f"/user/blocks/{bob['user']['id']}",
        headers=auth_headers(alice["access_token"]),
    )
    second = client.post(
        f"/user/blocks/{bob['user']['id']}",
        headers=auth_headers(alice["access_token"]),
    )

    assert first.status_code == 200
    assert second.status_code == 400


def test_list_blocked_users(client: TestClient):
    """User can list blocked users"""
    alice = register_user(client, "listblock_a")
    bob = register_user(client, "listblock_b")
    client.post(
        f"/user/blocks/{bob['user']['id']}",
        headers=auth_headers(alice["access_token"]),
    )
    resp = client.get("/user/me/blocks", headers=auth_headers(alice["access_token"]))
    assert resp.status_code == 200
    blocks = resp.json()
    assert len(blocks) == 1
    assert blocks[0]["user_id"] == bob["user"]["id"]


def test_unblock_user(client: TestClient):
    """User can unblock a user"""
    alice = register_user(client, "unblock_alice")
    bob = register_user(client, "unblock_bob")
    client.post(
        f"/user/blocks/{bob['user']['id']}",
        headers=auth_headers(alice["access_token"]),
    )
    resp = client.delete(
        f"/user/blocks/{bob['user']['id']}",
        headers=auth_headers(alice["access_token"]),
    )
    assert resp.status_code == 204
    blocks_resp = client.get(
        "/user/me/blocks", headers=auth_headers(alice["access_token"])
    )
    assert len(blocks_resp.json()) == 0


def test_blocked_users_cannot_become_friends(client: TestClient):
    """Blocked users cannot send friend requests to each other"""
    alice = register_user(client, "blocknf_alice")
    bob = register_user(client, "blocknf_bob")
    client.post(
        f"/user/blocks/{bob['user']['id']}",
        headers=auth_headers(alice["access_token"]),
    )
    resp = client.post(
        f"/user/friends/request/{alice['user']['id']}",
        headers=auth_headers(bob["access_token"]),
    )
    assert resp.status_code == 403


def test_blocking_user_clears_friendship_and_pending_requests(client: TestClient):
    alice = register_user(client, "blockclear_alice")
    bob = register_user(client, "blockclear_bob")
    charlie = register_user(client, "blockclear_charlie")

    accepted = client.post(
        f"/user/friends/request/{bob['user']['id']}",
        headers=auth_headers(alice["access_token"]),
    )
    assert accepted.status_code == 200
    accept_resp = client.patch(
        f"/user/friends/request/{accepted.json()['id']}?action=accept",
        headers=auth_headers(bob["access_token"]),
    )
    assert accept_resp.status_code == 200

    pending = client.post(
        f"/user/friends/request/{alice['user']['id']}",
        headers=auth_headers(charlie["access_token"]),
    )
    assert pending.status_code == 200

    block_friend = client.post(
        f"/user/blocks/{bob['user']['id']}",
        headers=auth_headers(alice["access_token"]),
    )
    block_pending = client.post(
        f"/user/blocks/{charlie['user']['id']}",
        headers=auth_headers(alice["access_token"]),
    )

    assert block_friend.status_code == 200
    assert block_pending.status_code == 200

    alice_friends = client.get(
        "/user/me/friends",
        headers=auth_headers(alice["access_token"]),
    )
    alice_requests = client.get(
        "/user/me/friends/requests",
        headers=auth_headers(alice["access_token"]),
    )
    charlie_requests = client.get(
        "/user/me/friends/requests",
        headers=auth_headers(charlie["access_token"]),
    )

    assert alice_friends.status_code == 200
    assert alice_friends.json() == []
    assert alice_requests.status_code == 200
    assert alice_requests.json() == []
    assert charlie_requests.status_code == 200
    assert charlie_requests.json() == []


def test_privacy_friends_only_blocks_messages(client: TestClient):
    """Friends-only privacy blocks direct room creation and messages"""
    alice = register_user(client, "privdm_alice")
    bob = register_user(client, "privdm_bob")
    client.patch(
        "/user/me/preferences",
        headers=auth_headers(alice["access_token"]),
        json={"privacy_messaging": "friends_only"},
    )
    dm_resp = client.post(
        "/room/dm",
        headers=auth_headers(bob["access_token"]),
        json={"user_id": alice["user"]["id"]},
    )
    assert dm_resp.status_code == 403


def test_subscribers_and_friends_allows_subscriber_direct_messages(
    client: TestClient,
    monkeypatch,
):
    alice = register_user(client, "subpriv_alice")
    bob = register_user(client, "subpriv_bob")
    monkeypatch.setattr(
        "app.modules.subscriptions.service.settings.subscription_self_activation_enabled",
        True,
    )

    pref_resp = client.patch(
        "/user/me/preferences",
        headers=auth_headers(alice["access_token"]),
        json={"privacy_messaging": "subscribers_and_friends"},
    )
    assert pref_resp.status_code == 200

    denied_dm = client.post(
        "/room/dm",
        headers=auth_headers(bob["access_token"]),
        json={"user_id": alice["user"]["id"]},
    )
    assert denied_dm.status_code == 403

    activate_resp = client.post(
        "/subscriptions/activate",
        headers=auth_headers(bob["access_token"]),
        json={"plan_id": "premium_monthly", "days": 30},
    )
    assert activate_resp.status_code == 200

    allowed_dm = client.post(
        "/room/dm",
        headers=auth_headers(bob["access_token"]),
        json={"user_id": alice["user"]["id"]},
    )
    assert allowed_dm.status_code == 200


def test_privacy_friends_only_blocks_existing_dm_messages(client: TestClient):
    alice = register_user(client, "privmsg_alice")
    bob = register_user(client, "privmsg_bob")
    dm_resp = client.post(
        "/room/dm",
        headers=auth_headers(bob["access_token"]),
        json={"user_id": alice["user"]["id"]},
    )
    assert dm_resp.status_code == 200
    room_id = dm_resp.json()["id"]
    pref_resp = client.patch(
        "/user/me/preferences",
        headers=auth_headers(alice["access_token"]),
        json={"privacy_messaging": "friends_only"},
    )
    assert pref_resp.status_code == 200
    msg_resp = client.post(
        "/message",
        headers=auth_headers(bob["access_token"]),
        json={"room_id": room_id, "text": "hello"},
    )
    assert msg_resp.status_code == 403


def test_privacy_friends_only_blocks_calls(client: TestClient):
    alice = register_user(client, "privcall_alice")
    bob = register_user(client, "privcall_bob")
    pref_resp = client.patch(
        "/user/me/preferences",
        headers=auth_headers(alice["access_token"]),
        json={"privacy_calling": "friends_only"},
    )
    assert pref_resp.status_code == 200
    dm_resp = client.post(
        "/room/dm",
        headers=auth_headers(alice["access_token"]),
        json={"user_id": bob["user"]["id"]},
    )
    assert dm_resp.status_code == 200
    call_resp = client.post(
        f"/call/room/{dm_resp.json()['id']}/invite",
        headers=auth_headers(bob["access_token"]),
    )
    assert call_resp.status_code == 403


def test_privacy_group_invite_requires_friendship(client: TestClient):
    owner = register_user(client, "groupinvite_owner")
    target = register_user(client, "groupinvite_target")

    room = create_room(
        client,
        owner["access_token"],
        member_ids=[],
        name="group-privacy",
    )

    pref_resp = client.patch(
        "/user/me/preferences",
        headers=auth_headers(target["access_token"]),
        json={"privacy_group_invite": "friends_only"},
    )
    assert pref_resp.status_code == 200

    denied = client.post(
        f"/room/{room['id']}/members",
        headers=auth_headers(owner["access_token"]),
        json={"user_id": target["user"]["id"]},
    )
    assert denied.status_code == 403

    request_resp = client.post(
        f"/user/friends/request/{target['user']['id']}",
        headers=auth_headers(owner["access_token"]),
    )
    assert request_resp.status_code == 200
    accept_resp = client.patch(
        f"/user/friends/request/{request_resp.json()['id']}?action=accept",
        headers=auth_headers(target["access_token"]),
    )
    assert accept_resp.status_code == 200

    allowed = client.post(
        f"/room/{room['id']}/members",
        headers=auth_headers(owner["access_token"]),
        json={"user_id": target["user"]["id"]},
    )
    assert allowed.status_code == 200
    assert set(allowed.json()["member_ids"]) == {
        owner["user"]["id"],
        target["user"]["id"],
    }


def test_reverse_pending_friend_request_is_rejected(client: TestClient):
    alice = register_user(client, "reverse_alice")
    bob = register_user(client, "reverse_bob")
    first_resp = client.post(
        f"/user/friends/request/{bob['user']['id']}",
        headers=auth_headers(alice["access_token"]),
    )
    assert first_resp.status_code == 200
    reverse_resp = client.post(
        f"/user/friends/request/{alice['user']['id']}",
        headers=auth_headers(bob["access_token"]),
    )
    assert reverse_resp.status_code == 400


def test_cannot_send_request_to_self(client: TestClient):
    """Cannot send friend request to yourself"""
    alice = register_user(client, "self_alice")
    resp = client.post(
        f"/user/friends/request/{alice['user']['id']}",
        headers=auth_headers(alice["access_token"]),
    )
    assert resp.status_code == 400


def test_cannot_block_self(client: TestClient):
    """Cannot block yourself"""
    alice = register_user(client, "blockself_a")
    resp = client.post(
        f"/user/blocks/{alice['user']['id']}",
        headers=auth_headers(alice["access_token"]),
    )
    assert resp.status_code == 400
