from functools import lru_cache

from app.config import settings
from app.dragonfly.adapter import DragonflyAdapter
from app.dragonfly.service import DragonflyService


@lru_cache
def get_dragonfly_adapter_singleton() -> DragonflyAdapter:
    return DragonflyAdapter(
        url=settings.dragonfly_url,
        connect_timeout_seconds=settings.dragonfly_connect_timeout_seconds,
        socket_timeout_seconds=settings.dragonfly_socket_timeout_seconds,
    )


@lru_cache
def get_dragonfly_service_singleton() -> DragonflyService:
    return DragonflyService(
        adapter=get_dragonfly_adapter_singleton(),
        settings=settings,
    )
