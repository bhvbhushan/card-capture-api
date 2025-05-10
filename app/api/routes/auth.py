from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import JSONResponse
from app.controllers.auth_controller import (
    login_controller,
    read_current_user_controller
)

router = APIRouter(prefix="/auth", tags=["Auth"])

@router.post("/login")
async def login(credentials: dict):
    return await login_controller(credentials)

@router.get("/me")
async def read_current_user(request: Request):
    return await read_current_user_controller(request) 