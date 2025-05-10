from app.services.users_service import (
    get_current_user_service,
    list_users_service,
    invite_user_service,
    update_user_service
)

def get_current_user_controller(user):
    user_id = user.get("id") or user.get("user_id")
    return get_current_user_service(user_id)

def list_users_controller():
    return list_users_service()

def invite_user_controller(user, payload):
    return invite_user_service(user, payload)

def update_user_controller(user_id, update):
    return update_user_service(user_id, update) 