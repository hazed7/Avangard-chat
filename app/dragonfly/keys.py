import hashlib


def _idem_key_fragment(idempotency_key: str) -> str:
    return hashlib.sha256(idempotency_key.encode()).hexdigest()


def rl_auth_route(prefix: str, route: str, scope: str) -> str:
    return f"{prefix}:rl:auth:{route}:{scope}"


def rl_ws_connect(prefix: str, user_id: str, room_id: str) -> str:
    return f"{prefix}:rl:ws:connect:{user_id}:{room_id}"


def rl_ws_message(prefix: str, user_id: str, room_id: str) -> str:
    return f"{prefix}:rl:ws:message:{user_id}:{room_id}"


def abuse_auth_ip(prefix: str, ip: str) -> str:
    return f"{prefix}:abuse:auth:ip:{ip}"


def abuse_auth_user(prefix: str, username: str) -> str:
    return f"{prefix}:abuse:auth:user:{username}"


def abuse_ws_ip(prefix: str, ip: str) -> str:
    return f"{prefix}:abuse:ws:ip:{ip}"


def abuse_ws_handshake_ip(prefix: str, ip: str) -> str:
    return f"{prefix}:abuse:ws:handshake-ip:{ip}"


def abuse_ws_user(prefix: str, user_id: str) -> str:
    return f"{prefix}:abuse:ws:user:{user_id}"


def ws_room_channel(prefix: str, room_id: str) -> str:
    return f"{prefix}:ws:room:{room_id}"


def ws_room_channel_pattern(prefix: str) -> str:
    return f"{prefix}:ws:room:*"


def ws_presence_room_conn(
    prefix: str, room_id: str, user_id: str, connection_id: str
) -> str:
    return f"{prefix}:ws:presence:room:{room_id}:user:{user_id}:conn:{connection_id}"


def ws_presence_user_conn(
    prefix: str, user_id: str, room_id: str, connection_id: str
) -> str:
    return f"{prefix}:ws:presence:user:{user_id}:room:{room_id}:conn:{connection_id}"


def auth_revoked_jti(prefix: str, jti: str) -> str:
    return f"{prefix}:auth:revoked-jti:{jti}"


def auth_user_cutoff(prefix: str, user_id: str) -> str:
    return f"{prefix}:auth:user-cutoff:{user_id}"


def auth_refresh_session(prefix: str, session_id: str) -> str:
    return f"{prefix}:auth:refresh:session:{session_id}"


def auth_refresh_user_sessions(prefix: str, user_id: str) -> str:
    return f"{prefix}:auth:refresh:user-sessions:{user_id}"


def auth_refresh_lock(prefix: str, session_id: str) -> str:
    return f"{prefix}:auth:refresh:lock:{session_id}"


def authz_room_access(prefix: str, room_id: str, user_id: str) -> str:
    return f"{prefix}:authz:room-access:{room_id}:{user_id}"


def authz_room_access_pattern(prefix: str, room_id: str) -> str:
    return f"{prefix}:authz:room-access:{room_id}:*"


def authz_message_owner(prefix: str, message_id: str) -> str:
    return f"{prefix}:authz:message-owner:{message_id}"


def ws_message_idempotency(
    prefix: str, room_id: str, user_id: str, idempotency_key: str
) -> str:
    idem = _idem_key_fragment(idempotency_key)
    return f"{prefix}:ws:idempotency:{room_id}:{user_id}:{idem}"


def ws_message_idempotency_lock(
    prefix: str, room_id: str, user_id: str, idempotency_key: str
) -> str:
    idem = _idem_key_fragment(idempotency_key)
    return f"{prefix}:ws:idempotency-lock:{room_id}:{user_id}:{idem}"
