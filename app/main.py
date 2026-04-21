from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.openapi.utils import get_openapi

from app.core.database import init_db
from app.dragonfly.container import get_dragonfly_service_singleton
from app.router import auth, health, messages, rooms, users, ws
from app.typesense.container import get_typesense_service_singleton
from app.ws.manager import manager


@asynccontextmanager
async def lifespan(app: FastAPI):
    dragonfly = get_dragonfly_service_singleton()
    typesense = get_typesense_service_singleton()
    await dragonfly.startup()
    await typesense.startup()
    try:
        await init_db()
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
        }
    }
    schema["security"] = [{"BearerAuth": []}]
    app.openapi_schema = schema
    return app.openapi_schema


app.openapi = custom_openapi
