from fastapi import APIRouter, Depends, HTTPException, Request, Body
from fastapi.responses import JSONResponse
from app.controllers.auth_controller import (
    login_controller,
    read_current_user_controller,
    reset_password_controller
)

router = APIRouter(prefix="/auth", tags=["Auth"])

@router.post("/login")
async def login(credentials: dict):
    return await login_controller(credentials)

@router.get("/me")
async def read_current_user(request: Request):
    return await read_current_user_controller(request)

@router.post("/reset-password")
async def reset_password(payload: dict = Body(...)):
    return await reset_password_controller(payload) 