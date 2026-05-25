from aiohttp import ClientResponse
from fastapi import HTTPException
from openai import AsyncOpenAI

from app.modules.messages.model import Attachment
from app.platform.config.settings import settings
from app.platform.observability.logger import get_logger

logger = get_logger("audit")


class TranscriptionService:
    def __init__(
        self,
        open_ai_service: AsyncOpenAI,
    ):
        self.open_ai_service = open_ai_service

    async def transcript_voice_message(
        self, audio: ClientResponse, attachment: Attachment
    ) -> str:
        try:
            audio_bytes = await audio.read()
            transcription = await self.open_ai_service.audio.transcriptions.create(
                model=settings.ai_transcription_model,
                file=(attachment.filename, audio_bytes),
            )
            return transcription.text
        except Exception:
            logger.error(
                f"Couldn't transcribe audio file {attachment.id}",
                exc_info=True,
            )
            raise HTTPException(status_code=422, detail="Audio can't be transcribed")
