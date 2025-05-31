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

async def invite_user_service(user, payload):
    print("\n=== INVITE USER SERVICE START ===")
    print(f"👤 Service called by user: {user.get('email')} (ID: {user.get('id')})")
    print(f"👤 User object keys: {list(user.keys())}")
    print(f"👤 User object full: {user}")
    
    user_roles = user.get("role", [])
    print(f"🔑 User roles: {user_roles}")
    print(f"🔑 Checking if user has admin role...")
    
    if "admin" not in user_roles:
        print("❌ Only admins can invite users.")
        raise HTTPException(status_code=403, detail="Only admins can invite users.")
    
    print("✅ User has admin role")
    
    first_name = payload.get("first_name")
    last_name = payload.get("last_name")
    email = payload.get("email")
    role = payload.get("role", ["reviewer"])
    school_id = payload.get("school_id")
    
    print(f"📝 Processing invitation for:")
    print(f"  - Email: {email}")
    print(f"  - Name: {first_name} {last_name}")
    print(f"  - Roles: {role}")
    print(f"  - School ID: {school_id}")
    
    if not all([first_name, last_name, email, school_id]):
        print("❌ Missing required fields.")
        missing_fields = [field for field, value in {
            "first_name": first_name,
            "last_name": last_name,
            "email": email,
            "school_id": school_id
        }.items() if not value]
        print(f"❌ Missing fields: {missing_fields}")
        raise HTTPException(status_code=400, detail=f"Missing required fields: {', '.join(missing_fields)}")
    
    if isinstance(role, list):
        valid_roles = ["admin", "recruiter", "reviewer"]
        print(f"🔑 Validating roles: {role}")
        print(f"🔑 Valid roles allowed: {valid_roles}")
        
        invalid_roles = [r for r in role if r not in valid_roles]
        if invalid_roles:
            print(f"❌ Invalid roles specified: {invalid_roles}")
            raise HTTPException(status_code=400, detail=f"Invalid roles specified: {', '.join(invalid_roles)}")
    
    try:
        print(f"🔑 Attempting to invite user: {email}")
        print(f"📝 User metadata being sent:")
        print(f"  - first_name: {first_name}")
        print(f"  - last_name: {last_name}")
        print(f"  - role: {role}")
        print(f"  - school_id: {school_id}")
        
        result = invite_user_db(email, first_name, last_name, role, school_id)
        print(f"✅ Successfully invited user: {email}")
        print(f"📝 Created user metadata:")
        print(f"  User data: {result}")
        print("=== INVITE USER SERVICE END ===\n")
        return {"success": True, "user": result}
    except Exception as e:
        print("\n❌ ERROR IN INVITE USER SERVICE:")
        print(f"❌ Error type: {type(e)}")
        print(f"❌ Error message: {str(e)}")
        if hasattr(e, 'message'):
            print(f"❌ Error message attribute: {e.message}")
        if hasattr(e, 'details'):
            print(f"❌ Error details: {e.details}")
        if hasattr(e, '__dict__'):
            print(f"❌ Error dict: {e.__dict__}")
        import traceback
        print("❌ Stack trace:")
        print(traceback.format_exc())
        print("=== INVITE USER SERVICE END WITH ERROR ===\n")
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
    
    user_roles = user.get("role", [])
    if "admin" not in user_roles:
        print("❌ Only admins can delete users.")
        raise HTTPException(status_code=403, detail="Only admins can delete users.")
    
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