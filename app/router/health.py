from fastapi import APIRouter, Depends
from fastapi.responses import JSONResponse

from app.core.dependencies import get_dragonfly_service, get_typesense_service
from app.dragonfly.service import DragonflyService
from app.model.user import User
from app.typesense.service import TypesenseService

router = APIRouter()


@router.get("/live")
async def live() -> dict[str, str]:
    return {"status": "ok"}


@router.get("/ready")
async def ready(
    dragonfly: DragonflyService = Depends(get_dragonfly_service),
    typesense: TypesenseService = Depends(get_typesense_service),
):
    checks = {
        "mongodb": True,
        "dragonfly": True,
        "typesense": True,
    }

    try:
        await User.find_one(User.id == "__healthcheck__")
    except Exception:  # noqa: BLE001
        checks["mongodb"] = False

    try:
        checks["dragonfly"] = await dragonfly.ping()
    except Exception:  # noqa: BLE001
        checks["dragonfly"] = False

    try:
        checks["typesense"] = await typesense.ping()
    except Exception:  # noqa: BLE001
        checks["typesense"] = False

    status = "ok" if all(checks.values()) else "degraded"
    payload = {"status": status, "checks": checks}
    if status == "ok":
        return payload
    return JSONResponse(status_code=503, content=payload)
