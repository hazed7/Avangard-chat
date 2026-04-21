from typing import Any

import httpx


class TypesenseAdapter:
    def __init__(
        self,
        *,
        url: str,
        api_key: str,
        connect_timeout_seconds: float,
        read_timeout_seconds: float,
    ):
        self._url = url.rstrip("/")
        self._api_key = api_key
        self._connect_timeout_seconds = connect_timeout_seconds
        self._read_timeout_seconds = read_timeout_seconds
        self._client: httpx.AsyncClient | None = None

    async def startup(self) -> None:
        if self._client is not None:
            return
        self._client = httpx.AsyncClient(
            base_url=self._url,
            headers={"X-TYPESENSE-API-KEY": self._api_key},
            timeout=httpx.Timeout(
                connect=self._connect_timeout_seconds,
                read=self._read_timeout_seconds,
                write=self._read_timeout_seconds,
                pool=self._connect_timeout_seconds,
            ),
        )
        await self.ping()

    async def shutdown(self) -> None:
        if self._client is None:
            return
        await self._client.aclose()
        self._client = None

    async def ping(self) -> bool:
        response = await self._require_client().get("/health")
        return response.status_code == 200

    async def ensure_collection(
        self,
        *,
        collection: str,
        fields: list[dict[str, Any]],
        default_sorting_field: str,
    ) -> None:
        client = self._require_client()
        get_response = await client.get(f"/collections/{collection}")
        if get_response.status_code == 200:
            return
        if get_response.status_code != 404:
            get_response.raise_for_status()
        create_response = await client.post(
            "/collections",
            json={
                "name": collection,
                "fields": fields,
                "default_sorting_field": default_sorting_field,
            },
        )
        create_response.raise_for_status()

    async def upsert_document(
        self, *, collection: str, document: dict[str, Any]
    ) -> None:
        response = await self._require_client().post(
            f"/collections/{collection}/documents",
            params={"action": "upsert"},
            json=document,
        )
        response.raise_for_status()

    async def delete_document(self, *, collection: str, document_id: str) -> None:
        response = await self._require_client().delete(
            f"/collections/{collection}/documents/{document_id}",
        )
        if response.status_code in {200, 404}:
            return
        response.raise_for_status()

    async def search_documents(
        self,
        *,
        collection: str,
        query: str,
        filter_by: str,
        page: int = 1,
        per_page: int,
    ) -> tuple[list[dict[str, Any]], int]:
        response = await self._require_client().get(
            f"/collections/{collection}/documents/search",
            params={
                "q": query,
                "query_by": "text",
                "filter_by": filter_by,
                "sort_by": "created_at:desc",
                "page": page,
                "per_page": per_page,
            },
        )
        response.raise_for_status()
        payload = response.json()
        hits = payload.get("hits", [])
        documents: list[dict[str, Any]] = []
        for hit in hits:
            document = hit.get("document")
            if isinstance(document, dict):
                documents.append(document)
        found = payload.get("found", 0)
        if not isinstance(found, int):
            found = 0
        return documents, found

    def _require_client(self) -> httpx.AsyncClient:
        if self._client is None:
            raise RuntimeError("Typesense adapter is not started")
        return self._client
