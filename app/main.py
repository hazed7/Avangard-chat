from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.openapi.utils import get_openapi

from app.modules.auth import router as auth
from app.modules.messages import router as messages
from app.modules.rooms import router as rooms
from app.modules.system import health_router as health
from app.modules.system.database import init_db
from app.modules.users import router as users
from app.modules.ws import router as ws
from app.modules.ws.manager import manager
from app.platform.backends.dragonfly.container import get_dragonfly_service_singleton
from app.platform.backends.s3.container import get_s3_service_singleton
from app.platform.backends.typesense.container import get_typesense_service_singleton


@asynccontextmanager
async def lifespan(app: FastAPI):
    dragonfly = get_dragonfly_service_singleton()
    typesense = get_typesense_service_singleton()
    s3_service = get_s3_service_singleton()
    await dragonfly.startup()
    await typesense.startup()
    try:
        await init_db()
        await s3_service.init_s3()
        await manager.startup()
        yield
    finally:
        await manager.shutdown()
        await typesense.shutdown()
        await dragonfly.shutdown()


app = FastAPI(
    title="Avangard API",
    lifespan=lifespan,
)

app.include_router(auth.router, prefix="/auth", tags=["Auth"])
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
