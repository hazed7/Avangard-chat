from fastapi import APIRouter, Depends, HTTPException, Query, UploadFile
from starlette.responses import StreamingResponse

from app.modules.rooms.model import ChatRoom
from app.modules.system.dependencies import (
    get_dragonfly_service,
    get_s3_service,
    get_social_service,
    verify_token,
)
from app.modules.system.streaming_utils import stream_with_cleanup
from app.modules.users.model import User
from app.modules.users.preferences_model import UserPreferences
from app.modules.users.schemas import (
    UserProfileResponse,
    UserResponse,
    UserUpdateRequest,
    serialize_user_response,
)
from app.modules.users.social_service import SocialService
from app.platform.backends.dragonfly.service import DragonflyService
from app.platform.backends.s3.service import S3Service, s3_settings
from app.platform.http.errors import error_responses
from app.platform.persistence.links import linked_document_id

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


@router.patch(
    "/me",
    response_model=UserResponse,
    responses=error_responses(401, 404),
)
async def update_me(
    data: UserUpdateRequest,
    user: dict = Depends(verify_token),
):
    db_user = await User.find_one(User.id == user["sub"])
    if not db_user:
        raise HTTPException(status_code=404, detail="User not found")
    db_user.full_name = data.full_name
    await db_user.save()
    return serialize_user_response(db_user)


@router.get(
    "/search",
    response_model=list[UserResponse],
    responses=error_responses(401),
)
async def search_users(
    q: str = Query(min_length=1, max_length=64),
    limit: int = Query(20, ge=1, le=50),
    current_user: dict = Depends(verify_token),
    dragonfly: DragonflyService = Depends(get_dragonfly_service),
):
    del current_user
    pattern = q.replace("%", r"\%").replace("_", r"\_")
    regex = f".*{pattern}.*"
    users = await (
        User.find(
            {
                "$or": [
                    {"username": {"$regex": regex, "$options": "i"}},
                    {"full_name": {"$regex": regex, "$options": "i"}},
                ],
            }
        )
        .limit(limit)
        .to_list()
    )
    return [await _serialize_user_with_presence(user, dragonfly) for user in users]


@router.get(
    "/{user_id}/profile",
    response_model=UserProfileResponse,
    responses=error_responses(401, 404),
)
async def get_user_profile(
    user_id: str,
    current_user: dict = Depends(verify_token),
    dragonfly: DragonflyService = Depends(get_dragonfly_service),
    social_service: SocialService = Depends(get_social_service),
):
    viewer_id = current_user["sub"]
    result = await User.find_one(User.id == user_id)
    if not result:
        raise HTTPException(status_code=404, detail="User not found")

    is_online, last_time_online = await dragonfly.get_user_presence(result.id)
    prefs = await UserPreferences.find_one(UserPreferences.user_id == user_id)
    is_friend = await social_service.are_friends(viewer_id, user_id)
    (
        outgoing_pending,
        incoming_pending,
        outgoing_request_id,
        incoming_request_id,
    ) = await social_service.get_pending_request_state(
        viewer_id,
        user_id,
    )
    is_blocked_by_me = await social_service.is_blocked_by_user(viewer_id, user_id)
    has_blocked_me = await social_service.is_blocked_by_user(user_id, viewer_id)
    viewer_friend_ids = await social_service.get_friend_ids(viewer_id)
    target_friend_ids = await social_service.get_friend_ids(user_id)
    mutual_friends_count = len(viewer_friend_ids & target_friend_ids)
    shared_groups = await ChatRoom.find(ChatRoom.is_group == True).to_list()  # noqa: E712
    shared_groups_count = sum(
        1
        for room in shared_groups
        if viewer_id in {linked_document_id(member) for member in room.members}
        and user_id in {linked_document_id(member) for member in room.members}
    )
    friends_since = await social_service.get_friendship_since(viewer_id, user_id)

    return UserProfileResponse.model_validate(
        {
            "id": result.id,
            "username": result.username,
            "full_name": result.full_name,
            "avatar": result.avatar,
            "is_online": is_online,
            "created_at": result.created_at,
            "last_time_online": last_time_online or result.last_time_online,
            "bio": prefs.bio if prefs else None,
            "status_emoji": prefs.status_emoji if prefs else None,
            "is_friend": is_friend,
            "outgoing_friend_request_pending": outgoing_pending,
            "incoming_friend_request_pending": incoming_pending,
            "outgoing_friend_request_id": outgoing_request_id,
            "incoming_friend_request_id": incoming_request_id,
            "is_blocked_by_me": is_blocked_by_me,
            "has_blocked_me": has_blocked_me,
            "friends_since": friends_since,
            "mutual_friends_count": mutual_friends_count,
            "shared_groups_count": shared_groups_count,
        }
    )


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
    if file.size is not None and file.size > s3_settings.avatar_max_upload_size_bytes:
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
