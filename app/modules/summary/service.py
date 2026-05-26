from datetime import datetime
from typing import Optional

import openai
from beanie.operators import Eq
from fastapi import HTTPException
from openai import AsyncOpenAI

from app.modules.messages.model import Message
from app.modules.rooms.model import ChatRoom
from app.platform.config.settings import settings
from app.platform.persistence.links import linked_document_id
from app.platform.security.message_crypto import MessageCrypto

_client = AsyncOpenAI(
    api_key=settings.ai.api_key,
    base_url=settings.ai.base_url,
    timeout=30.0,
)

SYSTEM_PROMPT = (
    "You are a concise chat summarizer. "
    "Given a list of chat messages with timestamps, produce a brief summary "
    "(3-5 sentences) highlighting the key topics and decisions. "
    "Reply in the same language as the messages."
)

# Жёсткий потолок — даже если диапазон огромный
HARD_CAP = 100


class SummaryService:
    @staticmethod
    def _decrypt_message_text(crypto: MessageCrypto, message: Message) -> str:
        return crypto.decrypt(
            ciphertext=message.text_ciphertext,
            nonce=message.text_nonce,
            key_id=message.text_key_id,
            aad=message.text_aad,
            context={
                "room_id": linked_document_id(message.room),
                "sender_id": linked_document_id(message.sender),
            },
        )

    @staticmethod
    def _build_conditions(
        room,
        user_id: str,
        from_dt: Optional[datetime],
        to_dt: Optional[datetime],
        unread_only: bool,
    ) -> list:
        conditions: list = [
            Message.room.id == room.id,
            Eq(Message.is_deleted, False),
        ]

        if from_dt:
            conditions.append(Message.created_at >= from_dt)
        if to_dt:
            conditions.append(Message.created_at <= to_dt)

        if unread_only:
            # User.id — строка (Keycloak sub), не ObjectId.
            # Ищем документы, где user_id НЕ встречается в массиве ссылок read_by.
            # $not + $elemMatch корректно обрабатывает и пустой массив.
            conditions.append({"read_by": {"$not": {"$elemMatch": {"$id": user_id}}}})

        return conditions

    @staticmethod
    def _detect_mode(
        unread_only: bool,
        from_dt: Optional[datetime],
        to_dt: Optional[datetime],
    ) -> str:
        has_range = bool(from_dt or to_dt)
        if unread_only and has_range:
            return "unread+range"
        if unread_only:
            return "unread"
        if has_range:
            return "range"
        return "recent"

    @staticmethod
    async def summarize_room(
        room_id: str,
        user_id: str,
        crypto: MessageCrypto,
        from_dt: Optional[datetime] = None,
        to_dt: Optional[datetime] = None,
        unread_only: bool = False,
    ) -> tuple[str, int, bool, str]:
        """Returns (summary, count, was_capped, mode)"""

        room = await ChatRoom.get(room_id)
        if not room:
            return "Room not found.", 0, False, "none"

        conditions = SummaryService._build_conditions(
            room, user_id, from_dt, to_dt, unread_only
        )
        mode = SummaryService._detect_mode(unread_only, from_dt, to_dt)

        if mode == "recent":
            messages = (
                await Message.find(*conditions)
                .sort(-Message.created_at)
                .limit(settings.ai.summary_max_messages)
                .to_list()
            )
            messages.reverse()
            was_capped = False
        else:
            total_count = await Message.find(*conditions).count()
            messages = (
                await Message.find(*conditions)
                .sort(+Message.created_at)
                .limit(HARD_CAP)
                .to_list()
            )
            was_capped = total_count > HARD_CAP

        if not messages:
            label = "unread messages" if unread_only else "messages"
            return f"No {label} found for the given criteria.", 0, False, mode

        lines = []
        for msg in messages:
            await msg.fetch_link(Message.sender)
            sender = getattr(msg.sender, "username", "?")
            ts = msg.created_at.strftime("%d.%m %H:%M")

            plain = SummaryService._decrypt_message_text(crypto, msg)  # ← дешифруем
            max_chars = settings.ai.summary_max_chars_per_message
            text = plain[:max_chars]
            if len(plain) > max_chars:
                text += "…"

            lines.append(f"[{ts}] {sender}: {text}")

        chat_text = "\n".join(lines)

        try:
            response = await _client.chat.completions.create(
                model=settings.ai.summary_model,
                messages=[
                    {"role": "system", "content": SYSTEM_PROMPT},
                    {"role": "user", "content": f"Chat messages:\n\n{chat_text}"},
                ],
                max_tokens=300,
                temperature=0.3,
            )
        except openai.APITimeoutError as exc:
            raise HTTPException(
                status_code=504,
                detail="AI summarizer timed out, please try again later",
            ) from exc
        except openai.APIConnectionError as exc:
            raise HTTPException(
                status_code=502,
                detail="Could not reach AI summarizer",
            ) from exc
        except openai.RateLimitError as exc:
            raise HTTPException(
                status_code=503,
                detail="AI summarizer is temporarily unavailable, pls try again later",
            ) from exc
        except openai.InternalServerError as exc:
            raise HTTPException(
                status_code=502,
                detail="AI summarizer returned an error",
            ) from exc
        except openai.AuthenticationError as exc:
            raise HTTPException(
                status_code=503,
                detail="AI summarizer authentication failed",
            ) from exc
        except openai.BadRequestError as exc:
            raise HTTPException(
                status_code=400,
                detail="AI summarizer bad request",
            ) from exc
        except openai.APIStatusError as exc:
            raise HTTPException(
                status_code=exc.status_code,
                detail=exc.message,
            ) from exc

        summary = response.choices[0].message.content.strip()
        return summary, len(messages), was_capped, mode
