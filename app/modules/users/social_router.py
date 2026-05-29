from fastapi import APIRouter, Depends, Query

from app.modules.system.dependencies import get_social_service, verify_token
from app.modules.users.schemas import (
    BlockInfo,
    FriendInfo,
    FriendRequestResponse,
    UserPreferencesResponse,
    UserPreferencesUpdate,
    serialize_preferences,
)
from app.modules.users.social_service import SocialService

router = APIRouter()


@router.get("/me/preferences", response_model=UserPreferencesResponse)
async def get_preferences(
    user: dict = Depends(verify_token),
    social_service: SocialService = Depends(get_social_service),
):
    pref = await social_service.get_preferences(user["sub"])
    return serialize_preferences(pref)


@router.patch("/me/preferences", response_model=UserPreferencesResponse)
async def update_preferences(
    data: UserPreferencesUpdate,
    user: dict = Depends(verify_token),
    social_service: SocialService = Depends(get_social_service),
):
    pref = await social_service.update_preferences(user["sub"], data)
    return serialize_preferences(pref)


@router.get("/me/friends", response_model=list[FriendInfo])
async def get_friends(
    user: dict = Depends(verify_token),
    social_service: SocialService = Depends(get_social_service),
):
    return await social_service.get_friends(user["sub"])


@router.get("/me/friends/requests", response_model=list[FriendRequestResponse])
async def get_friend_requests(
    user: dict = Depends(verify_token),
    social_service: SocialService = Depends(get_social_service),
):
    return await social_service.get_pending_requests(user["sub"])


@router.post("/friends/request/{target_user_id}", response_model=FriendRequestResponse)
async def send_friend_request(
    target_user_id: str,
    user: dict = Depends(verify_token),
    social_service: SocialService = Depends(get_social_service),
):
    return await social_service.send_friend_request(user["sub"], target_user_id)


@router.patch("/friends/request/{request_id}", response_model=FriendRequestResponse)
async def respond_friend_request(
    request_id: str,
    action: str = Query(..., pattern="^(accept|reject)$"),
    user: dict = Depends(verify_token),
    social_service: SocialService = Depends(get_social_service),
):
    return await social_service.respond_to_request(user["sub"], request_id, action)


@router.delete("/friends/{friend_user_id}", status_code=204)
async def remove_friend(
    friend_user_id: str,
    user: dict = Depends(verify_token),
    social_service: SocialService = Depends(get_social_service),
):
    await social_service.remove_friend(user["sub"], friend_user_id)


@router.get("/me/blocks", response_model=list[BlockInfo])
async def get_blocked_users(
    user: dict = Depends(verify_token),
    social_service: SocialService = Depends(get_social_service),
):
    return await social_service.get_blocked_users(user["sub"])


@router.post("/blocks/{target_user_id}", response_model=BlockInfo)
async def block_user(
    target_user_id: str,
    user: dict = Depends(verify_token),
    social_service: SocialService = Depends(get_social_service),
):
    return await social_service.block_user(user["sub"], target_user_id)


@router.delete("/blocks/{target_user_id}", status_code=204)
async def unblock_user(
    target_user_id: str,
    user: dict = Depends(verify_token),
    social_service: SocialService = Depends(get_social_service),
):
    await social_service.unblock_user(user["sub"], target_user_id)
