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

SYSTEM_PROMPT = (
    "You are a message rewriter assistant. "
    "The user will provide a message and a rewriting instruction. "
    "Return ONLY the rewritten message — no explanations, no quotes, "
    "no preamble. Preserve the original language of the message."
)

MAX_INPUT_CHARS = 1000

logger = get_logger("audit")


class AIAssistService:
    @staticmethod
    async def rewrite(text: str, style: RewriteStyle) -> RewriteResponse:
        if len(text) > MAX_INPUT_CHARS:
            raise HTTPException(
                status_code=422,
                detail=f"Message is too long (max {MAX_INPUT_CHARS} characters)",
            )

        user_content = f"{STYLE_PROMPTS[style]}\n\nMessage:\n{text}"

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
            transcription = await _client.audio.transcriptions.create(
                model=settings.ai_transcription_model,
                file=(attachment.filename, audio_bytes),
            )
            return transcription.text
        except HTTPException:
            raise
        except Exception:
            logger.error(
                f"Couldn't transcribe audio file {attachment.id}",
                exc_info=True,
            )
            raise HTTPException(status_code=422, detail="Audio can't be transcribed")
