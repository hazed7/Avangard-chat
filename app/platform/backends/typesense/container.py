from functools import lru_cache

from app.platform.backends.typesense.adapter import TypesenseAdapter
from app.platform.backends.typesense.service import TypesenseService
from app.platform.config.settings import settings


@lru_cache
def get_typesense_adapter_singleton() -> TypesenseAdapter:
    return TypesenseAdapter(
        url=settings.typesense.url,
        api_key=settings.typesense.api_key,
        connect_timeout_seconds=settings.typesense.timeout.connect_seconds,
        read_timeout_seconds=settings.typesense.timeout.read_seconds,
    )


@lru_cache
def get_typesense_service_singleton() -> TypesenseService:
    return TypesenseService(
        adapter=get_typesense_adapter_singleton(),
        settings=settings,
    )
