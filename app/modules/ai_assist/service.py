import base64

import httpx
import openai
from aiohttp import ClientResponse
from fastapi import HTTPException
from openai import AsyncOpenAI

from app.modules.ai_assist.enums import STYLE_PROMPTS, RewriteStyle
from app.modules.ai_assist.schemas import RewriteResponse
from app.modules.messages.model import Attachment
from app.platform.config.settings import settings
from app.platform.observability.logger import get_logger

_client = AsyncOpenAI(
    api_key=settings.ai.api_key,
    base_url=settings.ai.base_url,
    timeout=20.0,
)

_client_transcription = httpx.AsyncClient(timeout=20.0)

SYSTEM_PROMPT = (
    "You are a message rewriting assistant for a Russian-language messenger. "
    "The user will provide a message and a rewriting instruction. "
    "Return only the rewritten message: no explanations, no quotes, "
    "no markdown, no preamble. Preserve the meaning, key facts, names, "
    "numbers, and intent unless the instruction explicitly asks to change tone "
    "or length. Do not add new facts. "
    "Output language rules: preserve the original language of the message. "
    "If the message is mixed or ambiguous and contains Cyrillic, answer in "
    "Russian."
)

MAX_INPUT_CHARS = 1000

logger = get_logger("audit")

MIME_TO_FORMAT = {
    "audio/mpeg": "mp3",
    "audio/mp3": "mp3",
    "audio/ogg": "ogg",
    "audio/ogg;codecs=opus": "ogg",
    "audio/wav": "wav",
    "audio/webm": "webm",
    "audio/webm;codecs=opus": "webm",
    "audio/aac": "aac",
    "audio/x-m4a": "m4a",
    "audio/mp4": "m4a",
    "audio/flac": "flac",
}


def _normalize_audio_format(content_type: str | None) -> str | None:
    if not content_type:
        return None
    direct = MIME_TO_FORMAT.get(content_type)
    if direct:
        return direct
    base = content_type.split(";", 1)[0].strip()
    return MIME_TO_FORMAT.get(base)


class AIAssistService:
    @staticmethod
    def _preferred_output_language(text: str) -> str:
        cyrillic = sum(1 for char in text if "\u0400" <= char <= "\u04ff")
        latin = sum(1 for char in text if ("a" <= char.lower() <= "z"))
        if cyrillic >= latin:
            return "Russian"
        return "the original message language"

    @staticmethod
    async def rewrite(text: str, style: RewriteStyle) -> RewriteResponse:
        if len(text) > MAX_INPUT_CHARS:
            raise HTTPException(
                status_code=422,
                detail=f"Message is too long (max {MAX_INPUT_CHARS} characters)",
            )

        preferred_language = AIAssistService._preferred_output_language(text)
        user_content = (
            f"{STYLE_PROMPTS[style]}\n"
            f"Preferred output language: {preferred_language}.\n\n"
            f"Message:\n{text}"
        )

        try:
            response = await _client.chat.completions.create(
                model=settings.ai.summary_model,
                messages=[
                    {"role": "system", "content": SYSTEM_PROMPT},
                    {"role": "user", "content": user_content},
                ],
                max_tokens=600,
                temperature=0.4,
            )
        except openai.APITimeoutError as exc:
            raise HTTPException(
                status_code=504,
                detail="AI rewriter timed out, please try again",
            ) from exc
        except openai.APIConnectionError as exc:
            raise HTTPException(
                status_code=502,
                detail="Could not reach AI rewriter",
            ) from exc
        except openai.RateLimitError as exc:
            raise HTTPException(
                status_code=503,
                detail="AI rewriter is temporarily unavailable, please try again later",
            ) from exc
        except openai.InternalServerError as exc:
            raise HTTPException(
                status_code=502,
                detail="AI rewriter returned an error",
            ) from exc
        except openai.BadRequestError as exc:
            raise HTTPException(
                status_code=400,
                detail="AI rewriter bad request",
            ) from exc
        except openai.AuthenticationError as exc:
            raise HTTPException(
                status_code=403,
                detail="AI rewriter forbidden",
            ) from exc
        except openai.APIStatusError as exc:
            raise HTTPException(
                status_code=exc.status_code,
                detail=exc.message,
            ) from exc

        rewritten = response.choices[0].message.content.strip()

        return RewriteResponse(
            original=text,
            rewritten=rewritten,
            style=style,
        )

    @staticmethod
    async def transcript_voice_message(
        audio: ClientResponse, attachment: Attachment
    ) -> str:
        try:
            audio_bytes = await audio.read()
            audio_format = _normalize_audio_format(attachment.content_type)
            if not audio_format:
                raise HTTPException(400, "Unsupported audio format for transcription")
            payload = {
                "input_audio": {
                    "data": base64.b64encode(audio_bytes).decode(),
                    "format": audio_format,
                },
                "model": settings.ai.transcription_model,
            }
            response = await _client_transcription.post(
                settings.ai.transcription_base_url,
                headers={
                    "Authorization": f"Bearer {settings.ai.transcription_api_key}",
                    "Content-Type": "application/json",
                },
                json=payload,
            )
            response.raise_for_status()
            data = response.json()
            return data["text"]
        except httpx.TimeoutException as exc:
            raise HTTPException(
                504, "Transcription timed out, please try again"
            ) from exc
        except httpx.ConnectError as exc:
            raise HTTPException(502, "Could not reach transcription service") from exc
        except httpx.HTTPStatusError as exc:
            raise HTTPException(
                status_code=exc.response.status_code,
                detail=exc.response.text,
            ) from exc
