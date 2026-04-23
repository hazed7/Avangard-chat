from functools import lru_cache

from app.platform.backends.livekit.adapter import LiveKitAdapter
from app.platform.backends.livekit.service import LiveKitService
from app.platform.config.settings import settings


@lru_cache
def get_livekit_adapter_singleton() -> LiveKitAdapter:
    return LiveKitAdapter(
        url=settings.livekit.api_url,
        connect_timeout_seconds=settings.livekit.timeout.connect_seconds,
        read_timeout_seconds=settings.livekit.timeout.read_seconds,
    )


@lru_cache
def get_livekit_service_singleton() -> LiveKitService:
    return LiveKitService(
        adapter=get_livekit_adapter_singleton(),
        settings=settings,
    )
