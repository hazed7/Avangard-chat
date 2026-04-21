from fastapi import APIRouter, Depends, HTTPException
from starlette.responses import StreamingResponse

from app.modules.system.dependencies import verify_token
from app.modules.users.model import User
from app.platform.backends.s3.service import download_file
from app.platform.config.settings import settings
from app.platform.http.errors import error_responses

router = APIRouter()
s3_settings = settings.s3


@router.get(
    "/avatar",
    response_model=StreamingResponse,
    responses=error_responses(400, 401, 404)
)
async def download_avatar(user_token: dict = Depends(verify_token)):
    user = User.find_one(User.id == user_token["sub"])
    if not user:
        raise HTTPException(status_code=404, detail="User not found")
    if not user.avatar:
        raise HTTPException(status_code=400, detail="Avatar is absent")
    response = await download_file(s3_settings.bucket_avatars, user.avatar)
    return StreamingResponse(
        response.content,
        media_type=response.headers.get("content-type", "application/octet-stream")
    )