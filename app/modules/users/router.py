from fastapi import APIRouter, Depends, HTTPException, UploadFile
from starlette.responses import StreamingResponse

from app.modules.system.dependencies import verify_token, get_s3_service
from app.modules.users.model import User
from app.modules.users.schemas import UserResponse, serialize_user_response
from app.platform.backends.s3.service import s3_settings, S3Service
from app.platform.http.errors import error_responses

router = APIRouter()


@router.get(
    "/me",
    response_model=UserResponse,
    responses=error_responses(401, 404),
)
async def get_me(user: dict = Depends(verify_token)):
    result = await User.find_one(User.id == user["sub"])
    if not result:
        raise HTTPException(status_code=404, detail="User not found")
    return serialize_user_response(result)


@router.get(
    "/{user_id}",
    response_model=UserResponse,
    responses=error_responses(401, 404),
)
async def get_user(user_id: str, user: dict = Depends(verify_token)):
    result = await User.find_one(User.id == user_id)
    if not result:
        raise HTTPException(status_code=404, detail="User not found")
    return serialize_user_response(result)


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
        content=response.content,
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
