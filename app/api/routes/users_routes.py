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
    return await get_current_user_controller(user)

@router.get("/users")
async def list_users(user=Depends(get_current_user)):
    return await list_users_controller(user)

@router.post("/invite-user")
async def invite_user(user=Depends(get_current_user), payload: dict = Body(...)):
    try:
        print(f"👤 Invite user request from: {user.get('email')}")
        
        # Trim whitespace from string fields (defensive programming)
        if "email" in payload and isinstance(payload["email"], str):
            payload["email"] = payload["email"].strip()
        if "first_name" in payload and isinstance(payload["first_name"], str):
            payload["first_name"] = payload["first_name"].strip()
        if "last_name" in payload and isinstance(payload["last_name"], str):
            payload["last_name"] = payload["last_name"].strip()
        
        # Validate required fields
        required_fields = ["email", "first_name", "last_name", "role", "school_id"]
        for field in required_fields:
            if field not in payload:
                print(f"❌ Missing required field: {field}")
                raise HTTPException(status_code=400, detail=f"Missing required field: {field}")
        
        # Check for empty strings after trimming
        if not payload["email"] or not payload["first_name"] or not payload["last_name"]:
            print(f"❌ Required fields cannot be empty after trimming whitespace")
            raise HTTPException(status_code=400, detail="Email, first name, and last name cannot be empty")

        # Validate roles array
        roles = payload["role"] if isinstance(payload["role"], list) else [payload["role"]]
        valid_roles = ["admin", "recruiter", "reviewer"]
        
        # Check if all roles are valid
        invalid_roles = [role for role in roles if role not in valid_roles]
        if invalid_roles:
            print(f"❌ Invalid roles found: {invalid_roles}")
            raise HTTPException(
                status_code=400, 
                detail=f"Invalid roles: {', '.join(invalid_roles)}. Must be one of: {', '.join(valid_roles)}"
            )

        # Update the payload with validated roles
        payload["role"] = roles
        
        # Call the service to handle the invitation
        result = await invite_user_controller(user, payload)
        print(f"✅ User invitation completed for: {payload['email']}")
        return result
    except Exception as e:
        print(f"❌ Error in invite user endpoint: {str(e)}")
        import traceback
        print(f"❌ Stack trace: {traceback.format_exc()}")
        raise HTTPException(status_code=500, detail=str(e))

@router.put("/users/{user_id}")
async def update_user(user_id: str, update: UserUpdateRequest):
    return await update_user_controller(user_id, update)

@router.delete("/users/{user_id}")
async def delete_user(user_id: str, user=Depends(get_current_user)):
    return await delete_user_controller(user, user_id) 