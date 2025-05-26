from fastapi import APIRouter, Depends, Body
from app.controllers.users_controller import (
    get_current_user_controller,
    list_users_controller,
    invite_user_controller,
    update_user_controller,
    delete_user_controller
)
from app.core.auth import get_current_user
from app.models.user import UserUpdateRequest  # Adjust import if needed

router = APIRouter(tags=["Users"])

@router.get("/me")
async def read_current_user(user=Depends(get_current_user)):
    return get_current_user_controller(user)

@router.get("/users")
async def list_users(user=Depends(get_current_user)):
    return list_users_controller()

@router.post("/invite-user")
async def invite_user(user=Depends(get_current_user), payload: dict = Body(...)):
    return invite_user_controller(user, payload)

@router.put("/users/{user_id}")
async def update_user(user_id: str, update: UserUpdateRequest):
    return update_user_controller(user_id, update)

@router.delete("/users/{user_id}")
async def delete_user(user_id: str, user=Depends(get_current_user)):
    return delete_user_controller(user, user_id) 