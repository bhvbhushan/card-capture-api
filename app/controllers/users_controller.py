from app.services.users_service import (
    get_user_profile,
    get_users,
    invite_user_service,
    update_user_service,
    delete_user_service
)

async def get_current_user_controller(user_id):
    return await get_user_profile(user_id)

async def list_users_controller(user):
    return await get_users(user)

async def invite_user_controller(user, payload):
    return await invite_user_service(payload, user)

async def update_user_controller(user_id, update):
    return await update_user_service(user_id, update)

async def delete_user_controller(user, user_id):
    return await delete_user_service(user_id, user) 