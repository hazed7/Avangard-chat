from typing import Any

import httpx


class LiveKitAdapter:
    def __init__(
        self,
        *,
        url: str,
        connect_timeout_seconds: float,
        read_timeout_seconds: float,
    ):
        self._url = url.rstrip("/")
        self._connect_timeout_seconds = connect_timeout_seconds
        self._read_timeout_seconds = read_timeout_seconds
        self._client: httpx.AsyncClient | None = None

    async def startup(self) -> None:
        if self._client is not None:
            return
        self._client = httpx.AsyncClient(
            base_url=self._url,
            timeout=httpx.Timeout(
                connect=self._connect_timeout_seconds,
                read=self._read_timeout_seconds,
                write=self._read_timeout_seconds,
                pool=self._connect_timeout_seconds,
            ),
        )

    async def shutdown(self) -> None:
        if self._client is None:
            return
        await self._client.aclose()
        self._client = None

    async def post_json(
        self,
        path: str,
        *,
        token: str,
        payload: dict[str, Any],
    ) -> httpx.Response:
        response = await self._require_client().post(
            path,
            headers={"Authorization": f"Bearer {token}"},
            json=payload,
        )
        return response

    def _require_client(self) -> httpx.AsyncClient:
        if self._client is None:
            raise RuntimeError("LiveKit adapter is not started")
        return self._client
