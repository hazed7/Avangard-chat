from datetime import datetime
from unittest.mock import AsyncMock, MagicMock, patch

import openai
import pytest
from fastapi import HTTPException

# ---------------------------------------------------------------------------
# Helpers / Factories
# ---------------------------------------------------------------------------


def _make_message(
    text: str = "Hello",
    sender_username: str = "alice",
    created_at: datetime = None,
    room_id: str = "room123",
    sender_id: str = "user456",
):
    """Build a minimal mock Message object."""
    msg = MagicMock()
    msg.text_ciphertext = b"cipher"
    msg.text_nonce = b"nonce"
    msg.text_key_id = "key1"
    msg.text_aad = b"aad"
    msg.created_at = created_at or datetime(2024, 1, 15, 10, 30)
    msg.sender = MagicMock()
    msg.sender.username = sender_username
    msg.room = MagicMock()
    msg.fetch_link = AsyncMock()
    msg.message_type = "text"
    msg.attachments = []
    return msg


def _make_room(room_id: str = "room123"):
    room = MagicMock()
    room.id = room_id
    return room


def _make_crypto(decrypted_text: str = "Hello world"):
    crypto = MagicMock()
    crypto.decrypt.return_value = decrypted_text
    return crypto


def _make_openai_response(content: str = "This is a summary."):
    choice = MagicMock()
    choice.message.content = f"  {content}  "  # intentional whitespace
    choice.finish_reason = "stop"
    response = MagicMock()
    response.choices = [choice]
    return response


# ---------------------------------------------------------------------------
# Tests for _detect_mode
# ---------------------------------------------------------------------------


class TestDetectMode:
    """Tests for the pure static helper _detect_mode."""

    def setup_method(self):
        # Import here so patching of settings happens before import
        from app.modules.summary.service import SummaryService

        self.svc = SummaryService

    def test_recent_when_no_filters(self):
        assert self.svc._detect_mode(False, None, None) == "recent"

    def test_unread_when_only_unread(self):
        assert self.svc._detect_mode(True, None, None) == "unread"

    def test_range_when_only_from_dt(self):
        assert self.svc._detect_mode(False, datetime.now(), None) == "range"

    def test_range_when_only_to_dt(self):
        assert self.svc._detect_mode(False, None, datetime.now()) == "range"

    def test_range_when_both_dates(self):
        assert self.svc._detect_mode(False, datetime.now(), datetime.now()) == "range"

    def test_unread_range_when_all_set(self):
        assert (
            self.svc._detect_mode(True, datetime.now(), datetime.now())
            == "unread+range"
        )

    def test_unread_range_when_unread_plus_from_dt(self):
        assert self.svc._detect_mode(True, datetime.now(), None) == "unread+range"

    def test_preferred_output_language_defaults_to_russian_for_cyrillic(self):
        assert self.svc._preferred_output_language("привет hello") == "Russian"

    def test_strip_reasoning_markup_removes_think_block(self):
        text = "<think>internal reasoning</think>\nКраткая сводка."
        assert self.svc._strip_reasoning_markup(text) == "Краткая сводка."


# ---------------------------------------------------------------------------
# Tests for _build_conditions
# ---------------------------------------------------------------------------

# ---------------------------------------------------------------------------
# Tests for _build_conditions
# ---------------------------------------------------------------------------


class TestBuildConditions:
    """
    _build_conditions строит список, где первые два элемента — ODM-выражения
    (их трогать нельзя без живого ODM), а остальные — наши Python-объекты.
    Патчим ODM-выражения через MagicMock, чтобы их создание не падало.
    """

    def setup_method(self):
        from app.modules.summary.service import SummaryService

        self.svc = SummaryService

    def _call(self, room=None, from_dt=None, to_dt=None, unread_only=False):
        room = room or _make_room()
        with patch("app.modules.summary.service.Message") as mock_msg:
            # ODM-выражения Message.room.id == ... и Message.is_deleted == ...
            # возвращают MagicMock — нам важно лишь количество и тип условий
            mock_msg.room.id.__eq__ = MagicMock(return_value=MagicMock())
            mock_msg.is_deleted.__eq__ = MagicMock(return_value=MagicMock())
            mock_msg.created_at.__ge__ = MagicMock(return_value=MagicMock())
            mock_msg.created_at.__le__ = MagicMock(return_value=MagicMock())
            return self.svc._build_conditions(room, "u1", from_dt, to_dt, unread_only)

    def test_base_conditions_always_present(self):
        conds = self._call()
        assert len(conds) == 2

    def test_from_dt_adds_condition(self):
        conds = self._call(from_dt=datetime(2024, 1, 1))
        assert len(conds) == 3

    def test_to_dt_adds_condition(self):
        conds = self._call(to_dt=datetime(2024, 12, 31))
        assert len(conds) == 3

    def test_both_dates_add_two_conditions(self):
        conds = self._call(from_dt=datetime(2024, 1, 1), to_dt=datetime(2024, 12, 31))
        assert len(conds) == 4

    def test_unread_adds_read_by_condition(self):
        conds = self._call(unread_only=True)
        assert len(conds) == 3
        unread_cond = conds[-1]
        assert isinstance(unread_cond, dict)
        assert "read_by" in unread_cond
        assert "$not" in unread_cond["read_by"]
        assert "$elemMatch" in unread_cond["read_by"]["$not"]

    def test_unread_elem_match_uses_correct_user_id(self):
        room = _make_room()
        with patch("app.modules.summary.service.Message"):
            conds = self.svc._build_conditions(room, "user_xyz", None, None, True)
        unread_cond = conds[-1]
        assert unread_cond["read_by"]["$not"]["$elemMatch"]["$id"] == "user_xyz"

    def test_all_filters_add_correct_count(self):
        conds = self._call(
            from_dt=datetime(2024, 1, 1),
            to_dt=datetime(2024, 12, 31),
            unread_only=True,
        )
        assert len(conds) == 5


# ---------------------------------------------------------------------------
# Tests for _decrypt_message_text
# ---------------------------------------------------------------------------


class TestDecryptMessageText:
    def setup_method(self):
        from app.modules.summary.service import SummaryService

        self.svc = SummaryService

    @patch(
        "app.platform.persistence.links.linked_document_id",
        side_effect=lambda x: str(x.id),
    )
    def test_decrypt_calls_crypto_with_correct_args(self, mock_linked):
        crypto = _make_crypto("decrypted!")
        msg = _make_message()
        msg.room.id = "room123"
        msg.sender.id = "user456"

        result = self.svc._decrypt_message_text(crypto, msg)

        assert result == "decrypted!"
        crypto.decrypt.assert_called_once_with(
            ciphertext=msg.text_ciphertext,
            nonce=msg.text_nonce,
            key_id=msg.text_key_id,
            aad=msg.text_aad,
            context={"room_id": "room123", "sender_id": "user456"},
        )


class TestMessageTextForSummary:
    def setup_method(self):
        from app.modules.summary.service import SummaryService

        self.svc = SummaryService

    def test_regular_message_uses_decrypted_text(self):
        crypto = _make_crypto("decrypted text")
        msg = _make_message()
        result = self.svc._message_text_for_summary(crypto, msg)
        assert result == "decrypted text"
        crypto.decrypt.assert_called_once()

    def test_voice_message_uses_saved_transcription(self):
        crypto = _make_crypto("should not be used")
        msg = _make_message()
        msg.message_type = "voice"
        msg.attachments = [MagicMock(kind="voice", transcription="готовая расшифровка")]

        result = self.svc._message_text_for_summary(crypto, msg)

        assert result == "готовая расшифровка"
        crypto.decrypt.assert_not_called()

    def test_voice_message_without_transcription_returns_none(self):
        crypto = _make_crypto("should not be used")
        msg = _make_message()
        msg.message_type = "voice"
        msg.attachments = [MagicMock(kind="voice", transcription=None)]

        result = self.svc._message_text_for_summary(crypto, msg)

        assert result is None
        crypto.decrypt.assert_not_called()


# ---------------------------------------------------------------------------
# Tests for summarize_room — main orchestration
# ---------------------------------------------------------------------------

SETTINGS_PATH = "app.modules.summary.service.settings"
CHATROOM_PATH = "app.modules.summary.service.ChatRoom"
MESSAGE_PATH = "app.modules.summary.service.Message"
CLIENT_PATH = "app.modules.summary.service._client"


@pytest.mark.asyncio
class TestSummarizeRoom:
    async def _call(
        self,
        room_id="room1",
        user_id="user1",
        crypto=None,
        from_dt=None,
        to_dt=None,
        unread_only=False,
    ):
        from app.modules.summary.service import SummaryService

        return await SummaryService.summarize_room(
            room_id=room_id,
            user_id=user_id,
            crypto=crypto or _make_crypto(),
            from_dt=from_dt,
            to_dt=to_dt,
            unread_only=unread_only,
        )

    # --- Room not found ---

    @patch(CHATROOM_PATH)
    async def test_returns_room_not_found_when_no_room(self, mock_room_cls):
        mock_room_cls.get = AsyncMock(return_value=None)

        summary, count, was_capped, mode = await self._call(room_id="missing")

        assert summary == "Room not found."
        assert count == 0
        assert was_capped is False
        assert mode == "none"

    # --- No messages ---

    @patch(CLIENT_PATH)
    @patch(SETTINGS_PATH)
    @patch(MESSAGE_PATH)
    @patch(CHATROOM_PATH)
    async def test_returns_no_messages_when_list_empty(
        self, mock_room_cls, mock_msg_cls, mock_settings, mock_client
    ):
        mock_room_cls.get = AsyncMock(return_value=_make_room())
        mock_settings.ai.summary_max_messages = 50
        _setup_message_query(mock_msg_cls, messages=[])

        summary, count, was_capped, mode = await self._call()

        assert "No messages" in summary
        assert count == 0

    @patch(CLIENT_PATH)
    @patch(SETTINGS_PATH)
    @patch(MESSAGE_PATH)
    @patch(CHATROOM_PATH)
    async def test_no_unread_messages_label(
        self, mock_room_cls, mock_msg_cls, mock_settings, mock_client
    ):
        mock_room_cls.get = AsyncMock(return_value=_make_room())
        mock_settings.ai.summary_max_messages = 50
        _setup_message_query(mock_msg_cls, messages=[], mode="unread")

        summary, count, was_capped, mode = await self._call(unread_only=True)

        assert "unread messages" in summary

    # --- Successful summarization (recent mode) ---

    @patch(CLIENT_PATH)
    @patch(SETTINGS_PATH)
    @patch(
        "app.platform.persistence.links.linked_document_id", side_effect=lambda x: "id"
    )
    @patch(MESSAGE_PATH)
    @patch(CHATROOM_PATH)
    async def test_recent_mode_returns_summary(
        self, mock_room_cls, mock_msg_cls, mock_linked, mock_settings, mock_client
    ):
        mock_room_cls.get = AsyncMock(return_value=_make_room())
        mock_settings.ai.summary_max_messages = 50
        mock_settings.ai.summary_max_chars_per_message = 500
        mock_settings.ai.summary_model = "gpt-4o-mini"

        msgs = [_make_message("Hi there", "alice"), _make_message("Hello!", "bob")]
        _setup_message_query(mock_msg_cls, messages=msgs)

        mock_client.chat = MagicMock()
        mock_client.chat.completions = MagicMock()
        mock_client.chat.completions.create = AsyncMock(
            return_value=_make_openai_response("Concise summary.")
        )

        summary, count, was_capped, mode = await self._call()

        assert summary == "Concise summary."
        assert count == 2
        assert was_capped is False
        assert mode == "recent"

    @patch(CLIENT_PATH)
    @patch(SETTINGS_PATH)
    @patch(
        "app.platform.persistence.links.linked_document_id", side_effect=lambda x: "id"
    )
    @patch(MESSAGE_PATH)
    @patch(CHATROOM_PATH)
    async def test_summary_prompt_requests_russian_for_cyrillic_chat(
        self, mock_room_cls, mock_msg_cls, mock_linked, mock_settings, mock_client
    ):
        mock_room_cls.get = AsyncMock(return_value=_make_room())
        mock_settings.ai.summary_max_messages = 50
        mock_settings.ai.summary_max_chars_per_message = 500
        mock_settings.ai.summary_model = "gpt-4o-mini"

        msgs = [_make_message("ignored", "alice")]
        _setup_message_query(mock_msg_cls, messages=msgs)

        captured = {}

        async def capture(**kwargs):
            captured["messages"] = kwargs["messages"]
            return _make_openai_response("Краткая сводка.")

        mock_client.chat = MagicMock()
        mock_client.chat.completions = MagicMock()
        mock_client.chat.completions.create = AsyncMock(side_effect=capture)

        await self._call(crypto=_make_crypto("привет как дела"))

        user_content = captured["messages"][1]["content"]
        assert "Preferred output language: Russian." in user_content

    @patch(CLIENT_PATH)
    @patch(SETTINGS_PATH)
    @patch(
        "app.platform.persistence.links.linked_document_id", side_effect=lambda x: "id"
    )
    @patch(MESSAGE_PATH)
    @patch(CHATROOM_PATH)
    async def test_summary_uses_saved_voice_transcription(
        self, mock_room_cls, mock_msg_cls, mock_linked, mock_settings, mock_client
    ):
        mock_room_cls.get = AsyncMock(return_value=_make_room())
        mock_settings.ai.summary_max_messages = 50
        mock_settings.ai.summary_max_chars_per_message = 500
        mock_settings.ai.summary_model = "qwen/qwen3-32b"

        msg = _make_message("ignored", "alice")
        msg.message_type = "voice"
        msg.attachments = [
            MagicMock(kind="voice", transcription="это сохраненная расшифровка")
        ]
        _setup_message_query(mock_msg_cls, messages=[msg])

        captured = {}

        async def capture(**kwargs):
            captured["messages"] = kwargs["messages"]
            return _make_openai_response("Краткая сводка.")

        mock_client.chat = MagicMock()
        mock_client.chat.completions = MagicMock()
        mock_client.chat.completions.create = AsyncMock(side_effect=capture)

        await self._call(crypto=_make_crypto("не должно использоваться"))

        user_content = captured["messages"][1]["content"]
        assert "это сохраненная расшифровка" in user_content
        assert "не должно использоваться" not in user_content

    @patch(CLIENT_PATH)
    @patch(SETTINGS_PATH)
    @patch(
        "app.platform.persistence.links.linked_document_id", side_effect=lambda x: "id"
    )
    @patch(MESSAGE_PATH)
    @patch(CHATROOM_PATH)
    async def test_summary_skips_voice_without_transcription(
        self, mock_room_cls, mock_msg_cls, mock_linked, mock_settings, mock_client
    ):
        mock_room_cls.get = AsyncMock(return_value=_make_room())
        mock_settings.ai.summary_max_messages = 50
        mock_settings.ai.summary_max_chars_per_message = 500
        mock_settings.ai.summary_model = "qwen/qwen3-32b"

        msg = _make_message("ignored", "alice")
        msg.message_type = "voice"
        msg.attachments = [MagicMock(kind="voice", transcription=None)]
        _setup_message_query(mock_msg_cls, messages=[msg])

        summary, count, was_capped, mode = await self._call(
            crypto=_make_crypto("не должно использоваться")
        )

        assert (
            summary
            == "No messages with text or saved transcriptions found for the given "
            "criteria."
        )
        assert count == 0
        assert was_capped is False
        assert mode == "recent"

    @patch(CLIENT_PATH)
    @patch(SETTINGS_PATH)
    @patch(
        "app.platform.persistence.links.linked_document_id", side_effect=lambda x: "id"
    )
    @patch(MESSAGE_PATH)
    @patch(CHATROOM_PATH)
    async def test_summary_strips_think_block_from_model_output(
        self, mock_room_cls, mock_msg_cls, mock_linked, mock_settings, mock_client
    ):
        mock_room_cls.get = AsyncMock(return_value=_make_room())
        mock_settings.ai.summary_max_messages = 50
        mock_settings.ai.summary_max_chars_per_message = 500
        mock_settings.ai.summary_model = "qwen/qwen3-32b"

        msgs = [_make_message("ignored", "alice")]
        _setup_message_query(mock_msg_cls, messages=msgs)

        mock_client.chat = MagicMock()
        mock_client.chat.completions = MagicMock()
        mock_client.chat.completions.create = AsyncMock(
            return_value=_make_openai_response(
                "<think>internal plan</think>\nКраткая сводка."
            )
        )

        summary, _, _, _ = await self._call(crypto=_make_crypto("привет"))

        assert summary == "Краткая сводка."

    @patch(CLIENT_PATH)
    @patch(SETTINGS_PATH)
    @patch(
        "app.platform.persistence.links.linked_document_id", side_effect=lambda x: "id"
    )
    @patch(MESSAGE_PATH)
    @patch(CHATROOM_PATH)
    async def test_summary_retries_with_shorter_prompt_on_length_finish_reason(
        self, mock_room_cls, mock_msg_cls, mock_linked, mock_settings, mock_client
    ):
        mock_room_cls.get = AsyncMock(return_value=_make_room())
        mock_settings.ai.summary_max_messages = 50
        mock_settings.ai.summary_max_chars_per_message = 500
        mock_settings.ai.summary_model = "qwen/qwen3-32b"

        msgs = [_make_message("ignored", "alice")]
        _setup_message_query(mock_msg_cls, messages=msgs)

        first = _make_openai_response("Оборванная сводка")
        first.choices[0].finish_reason = "length"
        second = _make_openai_response("Короткая законченная сводка.")
        second.choices[0].finish_reason = "stop"

        mock_client.chat = MagicMock()
        mock_client.chat.completions = MagicMock()
        mock_client.chat.completions.create = AsyncMock(side_effect=[first, second])

        summary, _, _, _ = await self._call(crypto=_make_crypto("привет"))

        assert summary == "Короткая законченная сводка."
        assert mock_client.chat.completions.create.await_count == 2

    # --- was_capped flag ---

    @patch(CLIENT_PATH)
    @patch(SETTINGS_PATH)
    @patch(
        "app.platform.persistence.links.linked_document_id", side_effect=lambda x: "id"
    )
    @patch(MESSAGE_PATH)
    @patch(CHATROOM_PATH)
    async def test_was_capped_true_when_total_exceeds_hard_cap(
        self, mock_room_cls, mock_msg_cls, mock_linked, mock_settings, mock_client
    ):
        from app.modules.summary.service import HARD_CAP

        mock_room_cls.get = AsyncMock(return_value=_make_room())
        mock_settings.ai.summary_max_chars_per_message = 500
        mock_settings.ai.summary_model = "gpt-4o-mini"

        msgs = [_make_message() for _ in range(HARD_CAP)]
        _setup_message_query(mock_msg_cls, messages=msgs, total_count=HARD_CAP + 10)

        # Патчим ODM-операторы сравнения чтобы from_dt не падал
        mock_msg_cls.created_at.__ge__ = MagicMock(return_value=MagicMock())
        mock_msg_cls.created_at.__le__ = MagicMock(return_value=MagicMock())

        mock_client.chat.completions.create = AsyncMock(
            return_value=_make_openai_response("Summary.")
        )

        _, _, was_capped, _ = await self._call(from_dt=datetime(2024, 1, 1))

        assert was_capped is True

    @patch(CLIENT_PATH)
    @patch(SETTINGS_PATH)
    @patch(
        "app.platform.persistence.links.linked_document_id", side_effect=lambda x: "id"
    )
    @patch(MESSAGE_PATH)
    @patch(CHATROOM_PATH)
    async def test_was_capped_false_when_total_within_cap(
        self, mock_room_cls, mock_msg_cls, mock_linked, mock_settings, mock_client
    ):
        mock_room_cls.get = AsyncMock(return_value=_make_room())
        mock_settings.ai.summary_max_chars_per_message = 500
        mock_settings.ai.summary_model = "gpt-4o-mini"

        msgs = [_make_message() for _ in range(5)]
        _setup_message_query(mock_msg_cls, messages=msgs, total_count=5)

        # Патчим ODM-операторы сравнения чтобы from_dt не падал
        mock_msg_cls.created_at.__ge__ = MagicMock(return_value=MagicMock())
        mock_msg_cls.created_at.__le__ = MagicMock(return_value=MagicMock())

        mock_client.chat.completions.create = AsyncMock(
            return_value=_make_openai_response("Summary.")
        )

        _, _, was_capped, _ = await self._call(from_dt=datetime(2024, 1, 1))

        assert was_capped is False

    # --- Text truncation ---

    @patch(CLIENT_PATH)
    @patch(SETTINGS_PATH)
    @patch(
        "app.platform.persistence.links.linked_document_id", side_effect=lambda x: "id"
    )
    @patch(MESSAGE_PATH)
    @patch(CHATROOM_PATH)
    async def test_long_message_is_truncated_with_ellipsis(
        self, mock_room_cls, mock_msg_cls, mock_linked, mock_settings, mock_client
    ):
        mock_room_cls.get = AsyncMock(return_value=_make_room())
        mock_settings.ai.summary_max_messages = 50
        mock_settings.ai.summary_max_chars_per_message = 10  # very short cap
        mock_settings.ai.summary_model = "gpt-4o-mini"

        long_text = "A" * 100
        crypto = _make_crypto(long_text)
        msgs = [_make_message()]
        _setup_message_query(mock_msg_cls, messages=msgs)

        captured_call = {}

        async def capture_create(**kwargs):
            captured_call["messages"] = kwargs["messages"]
            return _make_openai_response("Summary.")

        mock_client.chat.completions.create = capture_create

        await self._call(crypto=crypto)

        user_content = captured_call["messages"][1]["content"]
        # Should contain truncated text + ellipsis
        assert "AAAAAAAAAA…" in user_content

    # --- OpenAI error handling ---

    @patch(CLIENT_PATH)
    @patch(SETTINGS_PATH)
    @patch(
        "app.platform.persistence.links.linked_document_id", side_effect=lambda x: "id"
    )
    @patch(MESSAGE_PATH)
    @patch(CHATROOM_PATH)
    async def test_raises_504_on_timeout(
        self, mock_room_cls, mock_msg_cls, mock_linked, mock_settings, mock_client
    ):
        mock_room_cls.get = AsyncMock(return_value=_make_room())
        mock_settings.ai.summary_max_messages = 50
        mock_settings.ai.summary_max_chars_per_message = 500
        mock_settings.ai.summary_model = "gpt-4o-mini"
        _setup_message_query(mock_msg_cls, messages=[_make_message()])

        mock_client.chat.completions.create = AsyncMock(
            side_effect=openai.APITimeoutError(request=MagicMock())
        )

        with pytest.raises(HTTPException) as exc_info:
            await self._call()

        assert exc_info.value.status_code == 504

    @patch(CLIENT_PATH)
    @patch(SETTINGS_PATH)
    @patch(
        "app.platform.persistence.links.linked_document_id", side_effect=lambda x: "id"
    )
    @patch(MESSAGE_PATH)
    @patch(CHATROOM_PATH)
    async def test_raises_502_on_connection_error(
        self, mock_room_cls, mock_msg_cls, mock_linked, mock_settings, mock_client
    ):
        mock_room_cls.get = AsyncMock(return_value=_make_room())
        mock_settings.ai.summary_max_messages = 50
        mock_settings.ai.summary_max_chars_per_message = 500
        mock_settings.ai.summary_model = "gpt-4o-mini"
        _setup_message_query(mock_msg_cls, messages=[_make_message()])

        mock_client.chat.completions.create = AsyncMock(
            side_effect=openai.APIConnectionError(request=MagicMock())
        )

        with pytest.raises(HTTPException) as exc_info:
            await self._call()

        assert exc_info.value.status_code == 502
        assert "reach" in exc_info.value.detail

    @patch(CLIENT_PATH)
    @patch(SETTINGS_PATH)
    @patch(
        "app.platform.persistence.links.linked_document_id", side_effect=lambda x: "id"
    )
    @patch(MESSAGE_PATH)
    @patch(CHATROOM_PATH)
    async def test_raises_503_on_rate_limit(
        self, mock_room_cls, mock_msg_cls, mock_linked, mock_settings, mock_client
    ):
        mock_room_cls.get = AsyncMock(return_value=_make_room())
        mock_settings.ai.summary_max_messages = 50
        mock_settings.ai.summary_max_chars_per_message = 500
        mock_settings.ai.summary_model = "gpt-4o-mini"
        _setup_message_query(mock_msg_cls, messages=[_make_message()])

        mock_client.chat.completions.create = AsyncMock(
            side_effect=openai.RateLimitError(
                message="rate limit", response=MagicMock(), body={}
            )
        )

        with pytest.raises(HTTPException) as exc_info:
            await self._call()

        assert exc_info.value.status_code == 503

    @patch(CLIENT_PATH)
    @patch(SETTINGS_PATH)
    @patch(
        "app.platform.persistence.links.linked_document_id", side_effect=lambda x: "id"
    )
    @patch(MESSAGE_PATH)
    @patch(CHATROOM_PATH)
    async def test_raises_502_on_internal_server_error(
        self, mock_room_cls, mock_msg_cls, mock_linked, mock_settings, mock_client
    ):
        mock_room_cls.get = AsyncMock(return_value=_make_room())
        mock_settings.ai.summary_max_messages = 50
        mock_settings.ai.summary_max_chars_per_message = 500
        mock_settings.ai.summary_model = "gpt-4o-mini"
        _setup_message_query(mock_msg_cls, messages=[_make_message()])

        mock_client.chat.completions.create = AsyncMock(
            side_effect=openai.InternalServerError(
                message="internal error", response=MagicMock(), body={}
            )
        )

        with pytest.raises(HTTPException) as exc_info:
            await self._call()

        assert exc_info.value.status_code == 502
        assert "returned an error" in exc_info.value.detail


# ---------------------------------------------------------------------------
# Query builder helper (shared across tests)
# ---------------------------------------------------------------------------


def _setup_message_query(
    mock_msg_cls, messages: list, total_count: int = 0, mode: str = "recent"
):
    """
    Wire up the Message.find(...) fluent interface mock.

    mode="recent"  → sort().limit().to_list() returns messages
    mode="range"   → count() returns total_count, sort().limit().to_list()
        returns messages
    mode="unread"  → same as "range"
    """
    query = MagicMock()
    query.sort.return_value = query
    query.limit.return_value = query
    query.to_list = AsyncMock(return_value=messages)
    query.count = AsyncMock(return_value=total_count)
    mock_msg_cls.find.return_value = query
