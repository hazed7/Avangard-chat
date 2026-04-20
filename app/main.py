from fastapi import FastAPI, HTTPException, WebSocket, WebSocketDisconnect
from fastapi.openapi.utils import get_openapi
from contextlib import asynccontextmanager
from app.database import init_db
from app.router import users, rooms, messages
from app.ws.manager import manager
from app.dependencies import verify_token
from app.config import settings


@asynccontextmanager
async def lifespan(app: FastAPI):
    await init_db()
    yield


app = FastAPI(
    title="Avangard API",
    lifespan=lifespan,
    swagger_ui_oauth2_redirect_url="/oauth2-redirect",
    swagger_ui_init_oauth={
        "clientId": settings.keycloak_client_id,
        "realm": settings.keycloak_realm,
        "appName": "Avangard",
        "usePkceWithAuthorizationCodeGrant": True
    }
)

app.include_router(users.router, prefix="/user", tags=["Users"])
app.include_router(rooms.router, prefix="/room", tags=["Rooms"])
app.include_router(messages.router, prefix="/message", tags=["Messages"])


def custom_openapi():
    if app.openapi_schema:
        return app.openapi_schema
    schema = get_openapi(
        title="Avangard API",
        version="0.0.1",
        routes=app.routes
    )
    schema["components"]["securitySchemes"] = {
        "OAuth2": {
            "type": "oauth2",
            "flows": {
                "authorizationCode": {
                    "authorizationUrl": (
                        f"{settings.keycloak_public_url}/realms/{settings.keycloak_realm}/protocol/openid-connect/auth"
                    ),
                    "tokenUrl": (
                        f"{settings.keycloak_public_url}/realms/{settings.keycloak_realm}/protocol/openid-connect/token"
                    ),
                    "scopes": {
                        "openid": "OpenID Connect",
                        "profile": "Profile",
                        "email": "Email",
                    }
                }
            }
        }
    }
    schema["security"] = [{"OAuth2": ["openid"]}]
    app.openapi_schema = schema
    return app.openapi_schema


@app.websocket("/ws/{room_id}")
async def chat(websocket: WebSocket, room_id: str, token: str):
    try:
        await verify_token(token)
    except HTTPException:
        await websocket.close(code=1008)
        return

    await manager.connect(websocket, room_id)
    try:
        while True:
            data = await websocket.receive_json()
            await manager.broadcast(room_id, data)
    except WebSocketDisconnect:
        manager.disconnect(websocket, room_id)
