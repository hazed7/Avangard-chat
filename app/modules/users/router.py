from fastapi import APIRouter, Depends, HTTPException, UploadFile
from starlette.responses import StreamingResponse

from app.modules.system.dependencies import (
    get_dragonfly_service,
    get_s3_service,
    verify_token,
)
from app.modules.system.streaming_utils import stream_with_cleanup
from app.modules.users.model import User
from app.modules.users.schemas import UserResponse, serialize_user_response
from app.platform.backends.dragonfly.service import DragonflyService
from app.platform.backends.s3.service import S3Service, s3_settings
from app.platform.http.errors import error_responses

router = APIRouter()


async def _serialize_user_with_presence(
    user: User,
    dragonfly: DragonflyService,
) -> UserResponse:
    is_online, last_time_online = await dragonfly.get_user_presence(user.id)
    return serialize_user_response(user).model_copy(
        update={
            "is_online": is_online,
            "last_time_online": last_time_online or user.last_time_online,
        }
    )


@router.get(
    "/me",
    response_model=UserResponse,
    responses=error_responses(401, 404),
)
async def get_me(
    user: dict = Depends(verify_token),
    dragonfly: DragonflyService = Depends(get_dragonfly_service),
):
    result = await User.find_one(User.id == user["sub"])
    if not result:
        raise HTTPException(status_code=404, detail="User not found")
    return await _serialize_user_with_presence(result, dragonfly)


@router.get(
    "/{user_id}",
    response_model=UserResponse,
    responses=error_responses(401, 404),
)
async def get_user(
    user_id: str,
    current_user: dict = Depends(verify_token),
    dragonfly: DragonflyService = Depends(get_dragonfly_service),
):
    del current_user
    result = await User.find_one(User.id == user_id)
    if not result:
        raise HTTPException(status_code=404, detail="User not found")
    return await _serialize_user_with_presence(result, dragonfly)


@router.post(
    "/me/avatar",
    response_model=UserResponse,
    responses=error_responses(401, 404, 422),
)
async def upload_avatar(
    file: UploadFile,
    user_token: dict = Depends(verify_token),
    s3_service: S3Service = Depends(get_s3_service),
):
    user = await User.find_one(User.id == user_token["sub"])
    if not user:
        raise HTTPException(status_code=404, detail="User not found")
    if file.size > 50 * 1024 * 1024:
        raise HTTPException(status_code=422, detail="File too large")
    avatar_path = await s3_service.upload_user_avatar(user.id, file)
    if not avatar_path:
        raise HTTPException(status_code=422, detail="Image format not supported")

    if user.avatar:
        await s3_service.delete_file(
            bucket=s3_settings.bucket_avatars,
            object_name=user.avatar,
        )
    user.avatar = avatar_path
    await user.save()

    return serialize_user_response(user)


@router.get(
    "/me/avatar",
    responses=error_responses(400, 401, 404),
)
async def download_avatar(
    user_token: dict = Depends(verify_token),
    s3_service: S3Service = Depends(get_s3_service),
):
    user = await User.find_one(User.id == user_token["sub"])
    if not user:
        raise HTTPException(status_code=404, detail="User not found")
    if not user.avatar:
        raise HTTPException(status_code=400, detail="Avatar is absent")
    response = await s3_service.download_file(
        bucket=s3_settings.bucket_avatars,
        object_name=user.avatar,
    )
    return StreamingResponse(
        content=stream_with_cleanup(response=response),
        media_type=response.headers.get("content-type", "application/octet-stream"),
    )


@router.delete("/me/avatar", responses=error_responses(400, 401, 404))
async def delete_avatar(
    user_token: dict = Depends(verify_token),
    s3_service: S3Service = Depends(get_s3_service),
):
    user = await User.find_one(User.id == user_token["sub"])
    if not user:
        raise HTTPException(status_code=404, detail="User not found")
    avatar_path = user.avatar
    if not avatar_path:
        raise HTTPException(status_code=400, detail="Avatar is absent")
    await s3_service.delete_file(
        bucket=s3_settings.bucket_avatars,
        object_name=avatar_path,
    )
    user.avatar = None
    await user.save()
