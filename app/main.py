from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.openapi.utils import get_openapi

from app.modules.auth import router as auth
from app.modules.calls import router as calls
from app.modules.messages import router as messages
from app.modules.messages.unread.worker import UnreadCounterReconciliationWorker
from app.modules.rooms import router as rooms
from app.modules.system import health_router as health
from app.modules.system.cleanup_jobs.worker import CleanupJobWorker
from app.modules.system.database import init_db
from app.modules.system.dependencies import (
    get_cleanup_job_service,
    get_unread_counter_service,
)
from app.modules.users import router as users
from app.modules.ws import router as ws
from app.modules.ws.manager import manager
from app.platform.backends.dragonfly.container import get_dragonfly_service_singleton
from app.platform.backends.livekit.container import get_livekit_service_singleton
from app.platform.backends.typesense.container import get_typesense_service_singleton
from app.platform.config.settings import settings


@asynccontextmanager
async def lifespan(app: FastAPI):
    dragonfly = get_dragonfly_service_singleton()
    livekit = get_livekit_service_singleton()
    typesense = get_typesense_service_singleton()
    cleanup_job_worker = CleanupJobWorker(
        service=get_cleanup_job_service(),
        interval_seconds=settings.cleanup_job_worker_interval_seconds,
    )
    unread_reconcile_worker = UnreadCounterReconciliationWorker(
        service=get_unread_counter_service(),
        interval_seconds=settings.unread_reconcile_interval_seconds,
    )
    await dragonfly.startup()
    await livekit.startup()
    await typesense.startup()
    try:
        await init_db()
        await manager.startup()
        await cleanup_job_worker.startup()
        await unread_reconcile_worker.startup()
        yield
    finally:
        await unread_reconcile_worker.shutdown()
        await cleanup_job_worker.shutdown()
        await manager.shutdown()
        await typesense.shutdown()
        await livekit.shutdown()
        await dragonfly.shutdown()


app = FastAPI(
    title="Avangard API",
    lifespan=lifespan,
)

app.include_router(auth.router, prefix="/auth", tags=["Auth"])
app.include_router(calls.router, prefix="/call", tags=["Calls"])
app.include_router(health.router, prefix="/health", tags=["Health"])
app.include_router(users.router, prefix="/user", tags=["Users"])
app.include_router(rooms.router, prefix="/room", tags=["Rooms"])
app.include_router(messages.router, prefix="/message", tags=["Messages"])
app.include_router(ws.router, prefix="/ws", tags=["WebSockets"])


def custom_openapi():
    if app.openapi_schema:
        return app.openapi_schema
    schema = get_openapi(title="Avangard API", version="0.0.1", routes=app.routes)
    schema["components"]["securitySchemes"] = {
        "BearerAuth": {
            "type": "http",
            "scheme": "bearer",
            "bearerFormat": "JWT",
        },
        "HTTPBearer": {
            "type": "http",
            "scheme": "bearer",
        },
    }
    schema["security"] = [{"BearerAuth": []}]
    app.openapi_schema = schema
    return app.openapi_schema


app.openapi = custom_openapi
