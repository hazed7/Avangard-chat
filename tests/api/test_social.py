from fastapi.testclient import TestClient

from tests.helpers.auth import auth_headers, register_user


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
