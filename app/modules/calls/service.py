import base64
import json
from datetime import UTC, datetime

from bson import ObjectId
from bson.errors import InvalidId
from fastapi import HTTPException

from app.modules.calls.model import CallParticipantState, CallSession
from app.modules.calls.schemas import (
    CallCursorPageResponse,
    CallJoinCredentialsResponse,
    CallJoinResponse,
    CallSessionResponse,
    serialize_call_session_response,
)
from app.modules.rooms.model import ChatRoom
from app.modules.rooms.service import RoomService
from app.modules.users.model import User
from app.platform.backends.dragonfly.service import DragonflyService
from app.platform.backends.livekit.service import LiveKitService
from app.platform.persistence.links import linked_document_id, linked_document_ref


class CallService:
    def __init__(
        self,
        *,
        room_service: RoomService,
        dragonfly: DragonflyService,
        livekit: LiveKitService,
    ):
        self.room_service = room_service
        self.dragonfly = dragonfly
        self.livekit = livekit

    @staticmethod
    def _room_ref(room: ChatRoom):
        return linked_document_ref(ChatRoom.Settings.name, room.id)

    @staticmethod
    def _encode_cursor(call: CallSession) -> str:
        payload = {
            "created_at": call.created_at.isoformat(),
            "call_id": str(call.id),
        }
        raw = json.dumps(payload, separators=(",", ":")).encode()
        return base64.urlsafe_b64encode(raw).decode()

    @staticmethod
    def _decode_cursor(cursor: str) -> tuple[datetime, ObjectId]:
        try:
            decoded = base64.urlsafe_b64decode(cursor.encode()).decode()
            payload = json.loads(decoded)
            created_at = datetime.fromisoformat(payload["created_at"])
            call_id = ObjectId(payload["call_id"])
            return created_at, call_id
        except (ValueError, KeyError, TypeError, InvalidId, json.JSONDecodeError):
            raise HTTPException(status_code=400, detail="Invalid cursor")

    async def _get_user_or_404(self, user_id: str) -> User:
        user = await User.find_one(User.id == user_id)
        if not user:
            raise HTTPException(status_code=404, detail="User not found")
        return user

    async def _get_call_or_404(self, call_id: str) -> CallSession:
        call = await CallSession.get(call_id)
        if not call:
            raise HTTPException(status_code=404, detail="Call not found")
        return call

    async def _get_call_for_user(self, call_id: str, user_id: str) -> CallSession:
        call = await self._get_call_or_404(call_id)
        room_id = linked_document_id(call.room)
        await self.room_service.get_for_user(room_id, user_id)
        return call

    async def _get_live_call_for_room(self, room_id: str) -> CallSession | None:
        try:
            room_object_id = ObjectId(room_id)
        except InvalidId:
            return None
        return await (
            CallSession.find(
                {
                    "room": linked_document_ref(ChatRoom.Settings.name, room_object_id),
                    "status": {"$in": ["ringing", "active"]},
                }
            )
            .sort([("created_at", -1), ("_id", -1)])
            .first_or_none()
        )

    @staticmethod
    def _room_member_ids(room: ChatRoom) -> list[str]:
        member_ids = [linked_document_id(member) for member in room.members]
        creator_id = linked_document_id(room.created_by)
        if creator_id not in member_ids:
            member_ids.append(creator_id)
        return member_ids

    @staticmethod
    def _participant_state(
        call: CallSession,
        user_id: str,
    ) -> CallParticipantState | None:
        for state in call.participants:
            if state.user_id == user_id:
                return state
        return None

    @classmethod
    def _ensure_participant_state(
        cls,
        call: CallSession,
        user_id: str,
        *,
        invited_at: datetime,
    ) -> CallParticipantState:
        state = cls._participant_state(call, user_id)
        if state is not None:
            return state
        state = CallParticipantState(user_id=user_id, invited_at=invited_at)
        call.participants.append(state)
        return state

    @staticmethod
    def _joined_user_ids(call: CallSession) -> list[str]:
        return [
            state.user_id
            for state in call.participants
            if state.joined_at is not None and state.left_at is None
        ]

    @staticmethod
    def _mark_missed_participants(call: CallSession, *, ended_at: datetime) -> None:
        initiator_id = linked_document_id(call.initiated_by)
        for state in call.participants:
            if state.user_id == initiator_id:
                continue
            if (
                state.joined_at is None
                and state.left_at is None
                and state.missed_at is None
            ):
                state.missed_at = ended_at

    @staticmethod
    def _close_joined_participants(call: CallSession, *, ended_at: datetime) -> None:
        for state in call.participants:
            if state.joined_at is not None and state.left_at is None:
                state.left_at = ended_at

    @staticmethod
    def _has_joined_non_initiator(call: CallSession) -> bool:
        initiator_id = linked_document_id(call.initiated_by)
        return any(
            state.user_id != initiator_id
            and state.joined_at is not None
            and state.left_at is None
            for state in call.participants
        )

    @staticmethod
    def _has_pending_non_initiator(call: CallSession) -> bool:
        initiator_id = linked_document_id(call.initiated_by)
        return any(
            state.user_id != initiator_id and state.left_at is None
            for state in call.participants
        )

    async def _publish_event(
        self,
        *,
        room_id: str,
        event_type: str,
        payload: dict,
    ) -> None:
        await self.dragonfly.publish_room_event(
            room_id,
            {
                "type": event_type,
                "payload": payload,
            },
        )

    @staticmethod
    def _temporary_call_service_error() -> HTTPException:
        return HTTPException(
            status_code=503,
            detail="Temporary call service failure",
        )

    async def _end_call(
        self,
        call: CallSession,
        *,
        ended_by_id: str,
        ended_reason: str,
    ) -> CallSession:
        if call.status == "ended":
            return call

        room_id = linked_document_id(call.room)
        ended_at = datetime.now(UTC)
        await self.livekit.delete_room(room_id=room_id)
        call.status = "ended"
        call.ended_at = ended_at
        call.ended_by_id = ended_by_id
        call.ended_reason = ended_reason
        self._close_joined_participants(call, ended_at=ended_at)
        self._mark_missed_participants(call, ended_at=ended_at)
        await call.save()
        await self._publish_event(
            room_id=room_id,
            event_type="chat.call.ended",
            payload={
                "call_id": str(call.id),
                "room_id": room_id,
                "ended_by_id": ended_by_id,
                "ended_reason": ended_reason,
                "ts": int(ended_at.timestamp()),
            },
        )
        return call

    async def _ensure_call_manager(
        self,
        call: CallSession,
        *,
        actor_id: str,
    ) -> None:
        room_id = linked_document_id(call.room)
        room = await self.room_service.get_for_user(room_id, actor_id)
        room_owner_id = linked_document_id(room.created_by)
        initiator_id = linked_document_id(call.initiated_by)
        if actor_id not in {room_owner_id, initiator_id}:
            raise HTTPException(
                status_code=403,
                detail="You do not have permission to manage this call",
            )

    async def invite(self, *, room_id: str, user_id: str) -> CallSessionResponse:
        room = await self.room_service.get_for_user(room_id, user_id)
        existing = await self._get_live_call_for_room(room_id)
        if existing is not None:
            raise HTTPException(status_code=409, detail="A call is already active")

        initiator = await self._get_user_or_404(user_id)
        invited_at = datetime.now(UTC)
        participant_ids = self._room_member_ids(room)
        call = CallSession(
            room=room,
            initiated_by=initiator,
            livekit_room_name=self.livekit.room_name(room_id),
            participants=[
                CallParticipantState(user_id=participant_id, invited_at=invited_at)
                for participant_id in participant_ids
            ],
        )
        await call.insert()
        await self._publish_event(
            room_id=room_id,
            event_type="chat.call.invited",
            payload={
                "call_id": str(call.id),
                "room_id": room_id,
                "initiated_by_id": user_id,
                "kind": call.kind,
                "invited_user_ids": [
                    participant_id
                    for participant_id in participant_ids
                    if participant_id != user_id
                ],
                "ts": int(invited_at.timestamp()),
            },
        )
        return serialize_call_session_response(call)

    async def get_active(self, *, room_id: str, user_id: str) -> CallSessionResponse:
        await self.room_service.get_for_user(room_id, user_id)
        call = await self._get_live_call_for_room(room_id)
        if call is None:
            raise HTTPException(status_code=404, detail="Call not found")
        return serialize_call_session_response(call)

    async def join(self, *, call_id: str, user_id: str) -> CallJoinResponse:
        call = await self._get_call_for_user(call_id, user_id)
        if call.status == "ended":
            raise HTTPException(status_code=409, detail="Call has already ended")

        room_id = linked_document_id(call.room)
        room = await self.room_service.get(room_id)
        user = await self._get_user_or_404(user_id)
        now = datetime.now(UTC)
        state = self._ensure_participant_state(
            call, user_id, invited_at=call.created_at
        )
        should_publish_join = state.joined_at is None or state.left_at is not None
        if state.joined_at is None:
            state.joined_at = now
        state.left_at = None

        joined_user_ids = self._joined_user_ids(call)
        initiator_id = linked_document_id(call.initiated_by)
        if any(joined_user_id != initiator_id for joined_user_id in joined_user_ids):
            call.status = "active"
            call.answered_at = call.answered_at or now

        await call.save()
        if should_publish_join:
            await self._publish_event(
                room_id=room_id,
                event_type="chat.call.joined",
                payload={
                    "call_id": str(call.id),
                    "room_id": room_id,
                    "user_id": user_id,
                    "ts": int(now.timestamp()),
                },
            )

        token, expires_at = self.livekit.create_join_token(
            room_id=room_id,
            participant_identity=user.id,
            participant_name=user.username,
            metadata={
                "call_id": str(call.id),
                "kind": call.kind,
                "room_id": room_id,
                "room_name": room.name if room else None,
                "username": user.username,
            },
        )
        return CallJoinResponse(
            call=serialize_call_session_response(call),
            livekit=CallJoinCredentialsResponse(
                url=self.livekit.public_url,
                token=token,
                room_name=call.livekit_room_name,
                participant_identity=user.id,
                expires_at=expires_at,
            ),
        )

    async def mark_ringing(self, *, call_id: str, user_id: str) -> CallSessionResponse:
        call = await self._get_call_for_user(call_id, user_id)
        if call.status == "ended":
            raise HTTPException(status_code=409, detail="Call has already ended")

        now = datetime.now(UTC)
        state = self._ensure_participant_state(
            call, user_id, invited_at=call.created_at
        )
        if state.ringing_at is None:
            state.ringing_at = now
            await call.save()
            await self._publish_event(
                room_id=linked_document_id(call.room),
                event_type="chat.call.ringing",
                payload={
                    "call_id": str(call.id),
                    "room_id": linked_document_id(call.room),
                    "user_id": user_id,
                    "ts": int(now.timestamp()),
                },
            )
        return serialize_call_session_response(call)

    async def leave(self, *, call_id: str, user_id: str) -> CallSessionResponse:
        call = await self._get_call_for_user(call_id, user_id)
        room_id = linked_document_id(call.room)
        state = self._participant_state(call, user_id)
        if call.status == "ended" or state is None or state.left_at is not None:
            return serialize_call_session_response(call)

        initiator_id = linked_document_id(call.initiated_by)
        joined = state.joined_at is not None
        left_at = datetime.now(UTC)
        if joined:
            try:
                await self.livekit.remove_participant(room_id=room_id, user_id=user_id)
            except RuntimeError as exc:
                raise HTTPException(
                    status_code=503,
                    detail="Temporary call service failure",
                ) from exc
        state.left_at = left_at
        await call.save()
        reason = "left" if joined or user_id == initiator_id else "declined"
        await self._publish_event(
            room_id=room_id,
            event_type="chat.call.left",
            payload={
                "call_id": str(call.id),
                "room_id": room_id,
                "user_id": user_id,
                "reason": reason,
                "ts": int(left_at.timestamp()),
            },
        )

        should_end = False
        if user_id == initiator_id:
            should_end = not self._has_joined_non_initiator(call)
        else:
            should_end = not self._has_joined_non_initiator(
                call
            ) and not self._has_pending_non_initiator(call)

        if should_end:
            try:
                call = await self._end_call(
                    call,
                    ended_by_id=user_id,
                    ended_reason="ended" if call.answered_at else "cancelled",
                )
            except RuntimeError as exc:
                raise self._temporary_call_service_error() from exc
        return serialize_call_session_response(call)

    async def end(self, *, call_id: str, user_id: str) -> CallSessionResponse:
        call = await self._get_call_for_user(call_id, user_id)
        ended_reason = "ended" if call.answered_at else "cancelled"
        try:
            call = await self._end_call(
                call,
                ended_by_id=user_id,
                ended_reason=ended_reason,
            )
        except RuntimeError as exc:
            raise self._temporary_call_service_error() from exc
        return serialize_call_session_response(call)

    async def list_participants(
        self,
        *,
        call_id: str,
        user_id: str,
    ) -> CallSessionResponse:
        call = await self._get_call_for_user(call_id, user_id)
        return serialize_call_session_response(call)

    async def remove_participant(
        self,
        *,
        call_id: str,
        actor_id: str,
        target_user_id: str,
    ) -> CallSessionResponse:
        call = await self._get_call_for_user(call_id, actor_id)
        await self._ensure_call_manager(call, actor_id=actor_id)
        room_id = linked_document_id(call.room)
        state = self._participant_state(call, target_user_id)
        if state is None or call.status == "ended":
            return serialize_call_session_response(call)

        now = datetime.now(UTC)
        if state.joined_at is not None and state.left_at is None:
            try:
                await self.livekit.remove_participant(
                    room_id=room_id,
                    user_id=target_user_id,
                )
            except RuntimeError as exc:
                raise HTTPException(
                    status_code=503,
                    detail="Temporary call service failure",
                ) from exc
        if state.left_at is None:
            state.left_at = now
        await call.save()
        await self._publish_event(
            room_id=room_id,
            event_type="chat.call.left",
            payload={
                "call_id": str(call.id),
                "room_id": room_id,
                "user_id": target_user_id,
                "reason": "removed",
                "ts": int(now.timestamp()),
            },
        )

        if not self._has_joined_non_initiator(
            call
        ) and not self._has_pending_non_initiator(call):
            try:
                call = await self._end_call(
                    call,
                    ended_by_id=actor_id,
                    ended_reason="member_removed",
                )
            except RuntimeError as exc:
                raise self._temporary_call_service_error() from exc
        return serialize_call_session_response(call)

    async def list_room_history(
        self,
        *,
        room_id: str,
        user_id: str,
        limit: int,
        cursor: str | None,
    ) -> CallCursorPageResponse:
        room = await self.room_service.get_for_user(room_id, user_id)
        query: dict = {"room": self._room_ref(room)}
        if cursor:
            created_at, call_object_id = self._decode_cursor(cursor)
            query["$and"] = [
                {
                    "$or": [
                        {"created_at": {"$lt": created_at}},
                        {"created_at": created_at, "_id": {"$lt": call_object_id}},
                    ]
                }
            ]

        calls = await (
            CallSession.find(query)
            .sort([("created_at", -1), ("_id", -1)])
            .limit(limit + 1)
            .to_list()
        )
        has_more = len(calls) > limit
        page_items = calls[:limit]
        next_cursor = (
            self._encode_cursor(page_items[-1]) if has_more and page_items else None
        )
        return CallCursorPageResponse(
            items=[serialize_call_session_response(call) for call in page_items],
            next_cursor=next_cursor,
        )

    async def list_missed_calls(
        self,
        *,
        user_id: str,
        limit: int,
        cursor: str | None,
    ) -> CallCursorPageResponse:
        await self._get_user_or_404(user_id)
        query: dict = {
            "participants": {
                "$elemMatch": {
                    "user_id": user_id,
                    "missed_at": {"$ne": None},
                    "missed_acknowledged_at": None,
                }
            }
        }
        if cursor:
            created_at, call_object_id = self._decode_cursor(cursor)
            query["$and"] = [
                {
                    "$or": [
                        {"created_at": {"$lt": created_at}},
                        {"created_at": created_at, "_id": {"$lt": call_object_id}},
                    ]
                }
            ]

        calls = await (
            CallSession.find(query)
            .sort([("created_at", -1), ("_id", -1)])
            .limit(limit + 1)
            .to_list()
        )
        has_more = len(calls) > limit
        page_items = calls[:limit]
        next_cursor = (
            self._encode_cursor(page_items[-1]) if has_more and page_items else None
        )
        return CallCursorPageResponse(
            items=[serialize_call_session_response(call) for call in page_items],
            next_cursor=next_cursor,
        )

    async def acknowledge_missed_call(
        self,
        *,
        call_id: str,
        user_id: str,
    ) -> CallSessionResponse:
        call = await self._get_call_for_user(call_id, user_id)
        state = self._participant_state(call, user_id)
        if state is None or state.missed_at is None:
            raise HTTPException(status_code=400, detail="Call is not marked as missed")
        if state.missed_acknowledged_at is None:
            state.missed_acknowledged_at = datetime.now(UTC)
            await call.save()
        return serialize_call_session_response(call)

    async def handle_room_member_removed(
        self,
        *,
        room_id: str,
        user_id: str,
        actor_id: str,
    ) -> None:
        call = await self._get_live_call_for_room(room_id)
        if call is None:
            return
        await self.remove_participant(
            call_id=str(call.id),
            actor_id=actor_id,
            target_user_id=user_id,
        )

    async def handle_room_deleted(self, *, room_id: str, actor_id: str) -> None:
        call = await self._get_live_call_for_room(room_id)
        if call is None:
            return
        try:
            await self._end_call(
                call,
                ended_by_id=actor_id,
                ended_reason="room_deleted",
            )
        except RuntimeError:
            return
