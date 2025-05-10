from app.services.auth_service import (
    login_service,
    read_current_user_service
)

async def login_controller(credentials: dict):
    return await login_service(credentials)

async def read_current_user_controller(request):
    return await read_current_user_service(request) 