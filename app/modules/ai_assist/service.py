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

_client_transcription = AsyncOpenAI(
    api_key=settings.ai.transcription_api_key,
    base_url=settings.ai.transcription_base_url,
    timeout=20.0,
)

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
            transcription = await _client_transcription.audio.transcriptions.create(
                model=settings.ai.transcription_model,
                file=(attachment.filename, audio_bytes),
            )
            return transcription.text
        except openai.APITimeoutError as exc:
            raise HTTPException(
                status_code=504,
                detail="Transcription timed out, please try again",
            ) from exc
        except openai.APIConnectionError as exc:
            raise HTTPException(
                status_code=502,
                detail="Could not reach transcription service",
            ) from exc
        except openai.RateLimitError as exc:
            raise HTTPException(
                status_code=503,
                detail="Transcription service is temporarily unavailable",
            ) from exc
        except openai.InternalServerError as exc:
            raise HTTPException(
                status_code=502,
                detail="Transcription service returned an error",
            ) from exc
        except openai.BadRequestError as exc:
            raise HTTPException(
                status_code=400,
                detail="Transcription bad request",
            ) from exc
        except openai.AuthenticationError as exc:
            raise HTTPException(
                status_code=403,
                detail="Transcription service forbidden",
            ) from exc
        except openai.APIStatusError as exc:
            raise HTTPException(
                status_code=exc.status_code,
                detail=exc.message,
            ) from exc
