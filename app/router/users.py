from fastapi import APIRouter, Depends, HTTPException

from app.dependencies import verify_token
from app.model.user import User
from app.schema.user import UserResponse

router = APIRouter()


@router.get("/me", response_model=UserResponse)
async def get_me(user: dict = Depends(verify_token)):
    result = await User.find_one(User.id == user["sub"])
    if not result:
        raise HTTPException(status_code=404, detail="User not found")
    return result.to_response()


@router.get("/{user_id}", response_model=UserResponse)
async def get_user(user_id: str, user: dict = Depends(verify_token)):
    result = await User.find_one(User.id == user_id)
    if not result:
        raise HTTPException(status_code=404, detail="User not found")
    return result.to_response()
