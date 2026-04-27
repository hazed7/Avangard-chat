import asyncio

import httpx
from fastapi import APIRouter, Depends
from fastapi.responses import JSONResponse
from pymongo.errors import PyMongoError
from redis.exceptions import RedisError

from app.modules.system.dependencies import (
    get_dragonfly_service,
    get_livekit_service,
    get_typesense_service,
)
from app.modules.users.model import User
from app.platform.backends.dragonfly.service import DragonflyService
from app.platform.backends.livekit.service import LiveKitService
from app.platform.backends.typesense.service import TypesenseService

router = APIRouter()


@router.get("/live")
async def live() -> dict[str, str]:
    return {"status": "ok"}


@router.get("/ready")
async def ready(
    dragonfly: DragonflyService = Depends(get_dragonfly_service),
    livekit: LiveKitService = Depends(get_livekit_service),
    typesense: TypesenseService = Depends(get_typesense_service),
):
    checks = {
        "mongodb": True,
        "dragonfly": True,
        "livekit": True,
        "typesense": True,
    }

    try:
        await User.find_one(User.id == "__healthcheck__")
    except asyncio.CancelledError:
        raise
    except (PyMongoError, RuntimeError):
        checks["mongodb"] = False

    try:
        checks["dragonfly"] = await dragonfly.ping()
    except asyncio.CancelledError:
        raise
    except (OSError, TimeoutError, RuntimeError, RedisError):
        checks["dragonfly"] = False

    try:
        checks["livekit"] = await livekit.ping()
    except asyncio.CancelledError:
        raise
    except (OSError, TimeoutError, RuntimeError):
        checks["livekit"] = False

    try:
        checks["typesense"] = await typesense.ping()
    except asyncio.CancelledError:
        raise
    except (OSError, TimeoutError, RuntimeError, httpx.HTTPError):
        checks["typesense"] = False

    status = "ok" if all(checks.values()) else "degraded"
    payload = {"status": status, "checks": checks}
    if status == "ok":
        return payload
    return JSONResponse(status_code=503, content=payload)
