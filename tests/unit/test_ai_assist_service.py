from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi import HTTPException

from app.modules.ai_assist.enums import RewriteStyle

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _ok_response(text: str):
    r = MagicMock()
    r.choices[0].message.content = text
    return r


async def _call_rewrite(
    text: str,
    style: RewriteStyle,
    side_effect=None,
    response_text: str = "Rewritten.",
):
    from app.modules.ai_assist.service import AIAssistService

    with patch("app.modules.ai_assist.service._client") as mock_client:
        if side_effect:
            mock_client.chat.completions.create = AsyncMock(side_effect=side_effect)
        else:
            mock_client.chat.completions.create = AsyncMock(
                return_value=_ok_response(response_text)
            )
        return await AIAssistService.rewrite(text=text, style=style)


# ---------------------------------------------------------------------------
# RewriteStyle enum
# ---------------------------------------------------------------------------


class TestRewriteStyleEnum:
    def test_all_styles_have_prompts(self):
        from app.modules.ai_assist.enums import STYLE_PROMPTS

        for style in RewriteStyle:
            assert style in STYLE_PROMPTS
            assert len(STYLE_PROMPTS[style]) > 10

    def test_enum_values(self):
        assert RewriteStyle.FORMAL == "formal"
        assert RewriteStyle.CASUAL == "casual"
        assert RewriteStyle.SHORTER == "shorter"
        assert RewriteStyle.CLEARER == "clearer"
        assert RewriteStyle.FRIENDLY == "friendly"
        assert RewriteStyle.ASSERTIVE == "assertive"


# ---------------------------------------------------------------------------
# RewriteRequest schema validation
# ---------------------------------------------------------------------------


class TestRewriteRequestSchema:
    def test_valid(self):
        from app.modules.ai_assist.schemas import RewriteRequest

        req = RewriteRequest(text="Hello", style="formal")
        assert req.text == "Hello"
        assert req.style == RewriteStyle.FORMAL

    def test_empty_text_raises(self):
        from pydantic import ValidationError

        from app.modules.ai_assist.schemas import RewriteRequest

        with pytest.raises(ValidationError):
            RewriteRequest(text="", style="formal")

    def test_invalid_style_raises(self):
        from pydantic import ValidationError

        from app.modules.ai_assist.schemas import RewriteRequest

        with pytest.raises(ValidationError):
            RewriteRequest(text="hello", style="magic_tone")

    def test_text_too_long_raises(self):
        from pydantic import ValidationError

        from app.modules.ai_assist.schemas import RewriteRequest

        with pytest.raises(ValidationError):
            RewriteRequest(text="x" * 4001, style="formal")


# ---------------------------------------------------------------------------
# AIAssistService.rewrite — happy path
# ---------------------------------------------------------------------------


class TestRewriteHappyPath:
    @pytest.mark.asyncio
    async def test_returns_rewrite_response(self):
        result = await _call_rewrite(
            text="i think maybe we could meet",
            style=RewriteStyle.FORMAL,
            response_text="  I propose we schedule a meeting.  ",
        )
        assert result.rewritten == "I propose we schedule a meeting."
        assert result.original == "i think maybe we could meet"
        assert result.style == RewriteStyle.FORMAL

    @pytest.mark.asyncio
    async def test_strips_whitespace_from_response(self):
        result = await _call_rewrite(
            text="hi",
            style=RewriteStyle.CASUAL,
            response_text="\n\n  Hey!  \n",
        )
        assert result.rewritten == "Hey!"

    @pytest.mark.asyncio
    async def test_original_preserved_unchanged(self):
        original = "ну короче надо бы встретиться наверное"
        result = await _call_rewrite(text=original, style=RewriteStyle.SHORTER)
        assert result.original == original

    @pytest.mark.asyncio
    async def test_all_styles_accepted(self):
        for style in RewriteStyle:
            result = await _call_rewrite(
                text="Some message text",
                style=style,
                response_text=f"Rewritten as {style}",
            )
            assert result.style == style

    @pytest.mark.asyncio
    async def test_style_prompt_sent_to_llm(self):
        from app.modules.ai_assist.enums import STYLE_PROMPTS
        from app.modules.ai_assist.service import AIAssistService

        captured = {}

        async def capture(**kwargs):
            captured["messages"] = kwargs["messages"]
            return _ok_response("ok")

        with patch("app.modules.ai_assist.service._client") as mock_client:
            mock_client.chat.completions.create = AsyncMock(side_effect=capture)
            await AIAssistService.rewrite(
                text="test message", style=RewriteStyle.ASSERTIVE
            )

        user_content = captured["messages"][1]["content"]
        assert STYLE_PROMPTS[RewriteStyle.ASSERTIVE] in user_content
        assert "test message" in user_content


# ---------------------------------------------------------------------------
# AIAssistService.rewrite — input validation
# ---------------------------------------------------------------------------


class TestRewriteInputValidation:
    @pytest.mark.asyncio
    async def test_text_too_long_raises_422(self):
        from app.modules.ai_assist.service import MAX_INPUT_CHARS, AIAssistService

        long_text = "x" * (MAX_INPUT_CHARS + 1)
        with pytest.raises(HTTPException) as exc_info:
            await AIAssistService.rewrite(text=long_text, style=RewriteStyle.FORMAL)
        assert exc_info.value.status_code == 422

    @pytest.mark.asyncio
    async def test_text_at_limit_is_accepted(self):
        from app.modules.ai_assist.service import MAX_INPUT_CHARS

        result = await _call_rewrite(
            text="x" * MAX_INPUT_CHARS, style=RewriteStyle.FORMAL
        )
        assert result.rewritten == "Rewritten."


# ---------------------------------------------------------------------------
# AIAssistService.rewrite — OpenAI error handling
# ---------------------------------------------------------------------------


class TestRewriteErrorHandling:
    @pytest.mark.asyncio
    async def test_timeout_raises_504(self):
        import openai

        with pytest.raises(HTTPException) as exc_info:
            await _call_rewrite(
                text="hi",
                style=RewriteStyle.FORMAL,
                side_effect=openai.APITimeoutError(request=MagicMock()),
            )
        assert exc_info.value.status_code == 504

    @pytest.mark.asyncio
    async def test_connection_error_raises_502(self):
        import openai

        with pytest.raises(HTTPException) as exc_info:
            await _call_rewrite(
                text="hi",
                style=RewriteStyle.FORMAL,
                side_effect=openai.APIConnectionError(request=MagicMock()),
            )
        assert exc_info.value.status_code == 502

    @pytest.mark.asyncio
    async def test_rate_limit_raises_503(self):
        import openai

        mock_resp = MagicMock()
        mock_resp.status_code = 429
        mock_resp.headers = {}
        with pytest.raises(HTTPException) as exc_info:
            await _call_rewrite(
                text="hi",
                style=RewriteStyle.FORMAL,
                side_effect=openai.RateLimitError(
                    message="rate limit", response=mock_resp, body={}
                ),
            )
        assert exc_info.value.status_code == 503

    @pytest.mark.asyncio
    async def test_internal_server_error_raises_502(self):
        import openai

        mock_resp = MagicMock()
        mock_resp.status_code = 500
        mock_resp.headers = {}
        with pytest.raises(HTTPException) as exc_info:
            await _call_rewrite(
                text="hi",
                style=RewriteStyle.FORMAL,
                side_effect=openai.InternalServerError(
                    message="server error", response=mock_resp, body={}
                ),
            )
        assert exc_info.value.status_code == 502
