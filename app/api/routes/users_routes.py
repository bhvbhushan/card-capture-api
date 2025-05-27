from fastapi import APIRouter, Depends, Body, HTTPException
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
    try:
        print("📝 Received invite user request with payload:", payload)
        
        # Validate required fields
        required_fields = ["email", "first_name", "last_name", "role", "school_id"]
        for field in required_fields:
            if field not in payload:
                raise HTTPException(status_code=400, detail=f"Missing required field: {field}")

        # Validate roles array
        roles = payload["role"] if isinstance(payload["role"], list) else [payload["role"]]
        valid_roles = ["admin", "recruiter", "reviewer"]
        
        print("🔑 Validating roles:", roles)
        
        # Check if all roles are valid
        invalid_roles = [role for role in roles if role not in valid_roles]
        if invalid_roles:
            raise HTTPException(
                status_code=400, 
                detail=f"Invalid roles: {', '.join(invalid_roles)}. Must be one of: {', '.join(valid_roles)}"
            )

        # Update the payload with validated roles
        payload["role"] = roles

        print("✅ Roles validated, calling controller with payload:", payload)

        # Call the service to handle the invitation
        return await invite_user_controller(user, payload)
    except Exception as e:
        print("❌ Error in invite_user endpoint:", str(e))
        print("❌ Error type:", type(e))
        import traceback
        print("❌ Stack trace:", traceback.format_exc())
        raise HTTPException(status_code=500, detail=str(e))

@router.put("/users/{user_id}")
async def update_user(user_id: str, update: UserUpdateRequest):
    return update_user_controller(user_id, update)

@router.delete("/users/{user_id}")
async def delete_user(user_id: str, user=Depends(get_current_user)):
    return delete_user_controller(user, user_id) 