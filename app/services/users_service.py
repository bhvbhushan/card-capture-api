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
from app.utils.retry_utils import log_debug
import traceback

async def get_user_profile(user_id: str):
    """
    Get user profile by ID
    """
    try:
        log_debug(f"Fetching user profile for user_id: {user_id}", service="users")
        result = supabase_client.table("users").select("*").eq("id", user_id).execute()
        log_debug(f"User profile fetched for user_id: {user_id}", service="users")
        return result.data[0] if result.data else None
    except Exception as e:
        raise e

async def get_users():
    try:
        result = supabase_client.table("users").select("*").execute()
        log_debug(f"Fetched {len(result.data)} users", service="users")
        return result.data
    except Exception as e:
        log_debug(f"Error fetching users: {e}", service="users")
        raise e

async def invite_user_service(payload, user):
    log_debug("\n=== INVITE USER SERVICE START ===", service="users")
    log_debug(f"Service called by user: {user.get('email')} (ID: {user.get('id')})", service="users")
    log_debug(f"User object keys: {list(user.keys())}", service="users")
    log_debug(f"User object full: {user}", service="users")
    
    try:
        # Check admin permissions
        user_roles = user.get("role", [])
        log_debug(f"User roles: {user_roles}", service="users")
        log_debug("Checking if user has admin role...", service="users")
        
        if "admin" not in user_roles:
            log_debug("Only admins can invite users", service="users")
            return {"error": "Only admins can invite users"}, 403
        
        log_debug("User has admin role", service="users")
        
        # Extract payload data
        email = payload.email
        first_name = payload.first_name
        last_name = payload.last_name
        role = payload.role
        school_id = payload.school_id
        
        log_debug("Processing invitation for:", {
            "email": email,
            "name": f"{first_name} {last_name}",
            "roles": role,
            "school_id": school_id
        }, service="users")
        
        # Validate required fields
        if not all([email, first_name, last_name, role]):
            log_debug("Missing required fields", service="users")
            missing_fields = []
            if not email: missing_fields.append("email")
            if not first_name: missing_fields.append("first_name")
            if not last_name: missing_fields.append("last_name")
            if not role: missing_fields.append("role")
            log_debug(f"Missing fields: {missing_fields}", service="users")
            return {"error": f"Missing required fields: {', '.join(missing_fields)}"}, 400
        
        # Validate role
        valid_roles = ["admin", "user", "recruiter"]
        log_debug(f"Validating roles: {role}", service="users")
        log_debug(f"Valid roles allowed: {valid_roles}", service="users")
        
        invalid_roles = [r for r in role if r not in valid_roles]
        if invalid_roles:
            log_debug(f"Invalid roles specified: {invalid_roles}", service="users")
            return {"error": f"Invalid roles: {', '.join(invalid_roles)}"}, 400
        
        log_debug(f"Attempting to invite user: {email}", service="users")
        log_debug("User metadata being sent:", {
            "first_name": first_name,
            "last_name": last_name,
            "role": role,
            "school_id": school_id
        }, service="users")
        
        # Invite user via Supabase Auth
        result = supabase_client.auth.admin.invite_user_by_email(email, {
            "first_name": first_name,
            "last_name": last_name,
            "role": role,
            "school_id": school_id
        })
        log_debug(f"Successfully invited user: {email}", service="users")
        log_debug("Created user metadata:", {
            "user_data": result
        }, service="users")
        log_debug("=== INVITE USER SERVICE END ===\n", service="users")
        
        return {"success": True, "user": result}
        
    except Exception as e:
        log_debug("\n❌ ERROR IN INVITE USER SERVICE:", service="users")
        log_debug(f"Error type: {type(e)}", service="users")
        log_debug(f"Error message: {str(e)}", service="users")
        if hasattr(e, 'message'):
            log_debug(f"Error message attribute: {e.message}", service="users")
        if hasattr(e, 'details'):
            log_debug(f"Error details: {e.details}", service="users")
        if hasattr(e, '__dict__'):
            log_debug(f"Error dict: {e.__dict__}", service="users")
        
        log_debug("Stack trace:", service="users")
        log_debug(traceback.format_exc(), service="users")
        log_debug("=== INVITE USER SERVICE END WITH ERROR ===\n", service="users")
        
        return {"error": str(e)}, 500

async def update_user_service(user_id: str, payload):
    try:
        result = supabase_client.table("users").update(payload).eq("id", user_id).execute()
        if result.error:
            log_debug(f"Error updating user {user_id}: {result.error}", service="users")
        log_debug(f"User updated: {user_id}", service="users")
        return result
    except Exception as e:
        log_debug(f"Error updating user {user_id}: {e}", service="users")
        raise e

async def delete_user_service(user_id: str, user):
    log_debug(f"Delete user request - User object: {user}", service="users")
    log_debug(f"User role: {user.get('role')}", service="users")
    log_debug(f"User keys: {list(user.keys()) if user else 'None'}", service="users")
    
    try:
        # Check admin permissions
        user_roles = user.get("role", [])
        if "admin" not in user_roles:
            log_debug("Only admins can delete users", service="users")
            return {"error": "Only admins can delete users"}, 403
        
        # Prevent self-deletion
        if user.get("id") == user_id:
            log_debug("Users cannot delete themselves", service="users")
            return {"error": "Users cannot delete themselves"}, 400
        
        log_debug(f"Attempting to delete user: {user_id}", service="users")
        # Delete user via Supabase Auth Admin API
        result = supabase_client.auth.admin.delete_user(user_id)
        log_debug(f"Successfully deleted user: {user_id}", service="users")
        return {"success": True}
        
    except Exception as e:
        log_debug(f"Error deleting user {user_id}: {str(e)}", service="users")
        log_debug(f"Error type: {type(e)}", service="users")
        log_debug(f"Error details: {e.__dict__ if hasattr(e, '__dict__') else 'No details available'}", service="users")
        return {"error": str(e)}, 500 