from fastapi.responses import JSONResponse
from fastapi import HTTPException
from app.repositories.users_repository import (
    get_user_profile_by_id,
    list_users_db,
    invite_user_db,
    update_user_db,
    delete_user_db
)
from app.core.clients import supabase_client, supabase_auth

def get_current_user_service(user_id):
    print(f"🔍 Fetching user profile for user_id: {user_id}")
    profile = get_user_profile_by_id(supabase_client, user_id)
    print(f"✅ User profile fetched for user_id: {user_id}")
    return {"profile": profile}

def list_users_service():
    try:
        users = list_users_db(supabase_client)
        print(f"✅ Fetched {len(users)} users.")
        return {"users": users}
    except Exception as e:
        print(f"❌ Error fetching users: {e}")
        raise HTTPException(status_code=500, detail=f"Error fetching users: {e}")

def invite_user_service(user, payload):
    if user.get("role") != "admin":
        print("❌ Only admins can invite users.")
        raise HTTPException(status_code=403, detail="Only admins can invite users.")
    first_name = payload.get("first_name")
    last_name = payload.get("last_name")
    email = payload.get("email")
    role = payload.get("role", "user")
    school_id = payload.get("school_id")
    if not all([first_name, last_name, email, school_id]):
        print("❌ Missing required fields.")
        raise HTTPException(status_code=400, detail="Missing required fields.")
    try:
        print(f"🔑 Attempting to invite user: {email}")
        print(f"📝 User metadata being sent:")
        print(f"  - first_name: {first_name}")
        print(f"  - last_name: {last_name}")
        print(f"  - role: {role}")
        print(f"  - school_id: {school_id}")
        result = invite_user_db(supabase_auth, email, first_name, last_name, role, school_id)
        print(f"✅ Successfully invited user: {email}")
        print(f"📝 Created user metadata:")
        print(f"  User metadata: {result.user.user_metadata}")
        print(f"  App metadata: {result.user.app_metadata}")
        return {"success": True, "user_id": result.user.id}
    except Exception as e:
        print(f"❌ Error inviting user: {str(e)}")
        print(f"❌ Error type: {type(e)}")
        print(f"❌ Error details: {e.__dict__ if hasattr(e, '__dict__') else 'No details available'}")
        raise HTTPException(status_code=500, detail=f"Error inviting user: {str(e)}")

def update_user_service(user_id, update):
    try:
        result = update_user_db(supabase_client, user_id, update)
        if hasattr(result, 'error') and result.error:
            print(f"❌ Error updating user {user_id}: {result.error}")
            raise Exception(result.error)
        print(f"✅ User updated: {user_id}")
        return {"success": True}
    except Exception as e:
        print(f"❌ Error updating user {user_id}: {e}")
        return JSONResponse(status_code=500, content={"error": str(e)})

def delete_user_service(user, user_id):
    print(f"🔍 Delete user request - User object: {user}")
    print(f"🔍 User role: {user.get('role')}")
    print(f"🔍 User keys: {list(user.keys()) if user else 'None'}")
    
    if user.get("role") != "admin":
        print("❌ Only admins can delete users.")
        raise HTTPException(status_code=403, detail="Only admins can delete users.")
    
    # Prevent self-deletion
    if user.get("id") == user_id or user.get("user_id") == user_id:
        print("❌ Users cannot delete themselves.")
        raise HTTPException(status_code=400, detail="You cannot delete your own account.")
    
    try:
        print(f"🗑️ Attempting to delete user: {user_id}")
        result = delete_user_db(supabase_auth, supabase_client, user_id)
        print(f"✅ Successfully deleted user: {user_id}")
        return {"success": True, "message": "User deleted successfully"}
    except Exception as e:
        print(f"❌ Error deleting user {user_id}: {str(e)}")
        print(f"❌ Error type: {type(e)}")
        print(f"❌ Error details: {e.__dict__ if hasattr(e, '__dict__') else 'No details available'}")
        raise HTTPException(status_code=500, detail=f"Error deleting user: {str(e)}") 