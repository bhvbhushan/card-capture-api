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
    return await list_users_controller()

@router.post("/invite-user")
async def invite_user(user=Depends(get_current_user), payload: dict = Body(...)):
    try:
        print("\n=== INVITE USER REQUEST START ===")
        print(f"🔑 Auth headers received")
        print(f"👤 Request from user: {user.get('email')} (ID: {user.get('id')})")
        print(f"👤 User roles: {user.get('role')}")
        print(f"📝 Raw payload received: {payload}")
        
        # Validate required fields
        required_fields = ["email", "first_name", "last_name", "role", "school_id"]
        for field in required_fields:
            if field not in payload:
                print(f"❌ Missing required field: {field}")
                raise HTTPException(status_code=400, detail=f"Missing required field: {field}")

        # Validate roles array
        roles = payload["role"] if isinstance(payload["role"], list) else [payload["role"]]
        valid_roles = ["admin", "recruiter", "reviewer"]
        
        print(f"🔑 Validating roles: {roles}")
        print(f"🔑 Valid roles allowed: {valid_roles}")
        
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
        print("✅ Roles validated")
        print("📝 Final payload being sent to controller:", payload)

        # Call the service to handle the invitation
        result = await invite_user_controller(user, payload)
        print("✅ Invite user controller completed successfully")
        print("📝 Controller response:", result)
        print("=== INVITE USER REQUEST END ===\n")
        return result
    except Exception as e:
        print("\n❌ ERROR IN INVITE USER ENDPOINT:")
        print(f"❌ Error type: {type(e)}")
        print(f"❌ Error message: {str(e)}")
        if hasattr(e, 'detail'):
            print(f"❌ Error detail: {e.detail}")
        import traceback
        print("❌ Stack trace:")
        print(traceback.format_exc())
        print("=== INVITE USER REQUEST END WITH ERROR ===\n")
        raise HTTPException(status_code=500, detail=str(e))

@router.put("/users/{user_id}")
async def update_user(user_id: str, update: UserUpdateRequest):
    return await update_user_controller(user_id, update)

@router.delete("/users/{user_id}")
async def delete_user(user_id: str, user=Depends(get_current_user)):
    return await delete_user_controller(user, user_id) 