from fastapi import APIRouter, Depends, HTTPException, UploadFile

from app.modules.system.dependencies import verify_token
from app.modules.users.model import User
from app.modules.users.schemas import UserResponse, serialize_user_response
from app.platform.backends.s3.service import upload_user_avatar
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
    responses=error_responses(400, 401, 404),
)
async def upload_avatar(file: UploadFile, user_token: dict = Depends(verify_token)):
    user = await User.find_one(User.id == user_token["sub"])
    if not user:
        raise HTTPException(status_code=404, detail="User not found")
    if file.content_type not in ["image/jpeg", "image/png", "image/webp"]:
        raise HTTPException(status_code=400, detail="Only JPEG, PNG, WEBP allowed")
    if file.size > 50 * 1024 * 1024:
        raise HTTPException(status_code=400, detail="File too large")
    object_name = await upload_user_avatar(
        user_id=user.id,
        file=file,
    )

    user.avatar = object_name
    await user.save()

    return serialize_user_response(user)

