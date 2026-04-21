from datetime import datetime

from fastapi import HTTPException

from app.core.config import Settings
from app.core.logger import get_logger
from app.typesense.adapter import TypesenseAdapter

logger = get_logger("typesense")


def _filter_value(value: str) -> str:
    escaped = value.replace("`", "\\`")
    return f"`{escaped}`"


class TypesenseService:
    def __init__(self, *, adapter: TypesenseAdapter, settings: Settings):
        self._adapter = adapter
        self._settings = settings
        self._collection = settings.typesense.collection_messages

    async def startup(self) -> None:
        await self._adapter.startup()
        await self._adapter.ensure_collection(
            collection=self._collection,
            fields=[
                {"name": "id", "type": "string"},
                {"name": "room_id", "type": "string", "facet": True},
                {"name": "sender_id", "type": "string"},
                {"name": "text", "type": "string"},
                {"name": "is_deleted", "type": "bool"},
                {"name": "created_at", "type": "int64"},
            ],
            default_sorting_field="created_at",
        )

    async def shutdown(self) -> None:
        await self._adapter.shutdown()

    async def ping(self) -> bool:
        return await self._adapter.ping()

    async def upsert_message(
        self,
        *,
        message_id: str,
        room_id: str,
        sender_id: str,
        text: str,
        created_at: datetime,
        is_deleted: bool,
    ) -> None:
        try:
            await self._adapter.upsert_document(
                collection=self._collection,
                document={
                    "id": message_id,
                    "room_id": room_id,
                    "sender_id": sender_id,
                    "text": text,
                    "is_deleted": is_deleted,
                    "created_at": int(created_at.timestamp()),
                },
            )
        except Exception as exc:  # noqa: BLE001
            await self._handle_failure(feature="upsert_message", exc=exc)

    async def delete_message(self, *, message_id: str) -> None:
        try:
            await self._adapter.delete_document(
                collection=self._collection,
                document_id=message_id,
            )
        except Exception as exc:  # noqa: BLE001
            await self._handle_failure(feature="delete_message", exc=exc)

    async def search_message_ids(
        self,
        *,
        query: str,
        room_ids: list[str],
        limit: int,
        offset: int,
    ) -> list[str]:
        if not room_ids:
            return []

        # Typesense is page-based. Fetch offset+limit from the first page and slice.
        fetch_count = min(max(offset + limit, 1), 250)
        room_filter = ",".join(_filter_value(room_id) for room_id in room_ids)
        filter_by = f"room_id:=[{room_filter}] && is_deleted:=false"

        try:
            documents = await self._adapter.search_documents(
                collection=self._collection,
                query=query,
                filter_by=filter_by,
                per_page=fetch_count,
            )
        except Exception as exc:  # noqa: BLE001
            await self._handle_failure(feature="search_message_ids", exc=exc)
            return []

        paged_documents = documents[offset : offset + limit]
        message_ids: list[str] = []
        for document in paged_documents:
            message_id = document.get("id")
            if isinstance(message_id, str) and message_id:
                message_ids.append(message_id)
        return message_ids

    async def _handle_failure(self, *, feature: str, exc: Exception) -> None:
        policy = self._settings.typesense.fail_policy
        logger.warning(
            "typesense_failure feature=%s policy=%s error=%s",
            feature,
            policy,
            exc,
        )
        if policy != "open":
            raise HTTPException(
                status_code=503,
                detail=f"Temporary search backend failure in {feature}",
            )
