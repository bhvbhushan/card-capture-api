from fastapi import HTTPException
from app.core.clients import supabase_client
import re

def get_user_profile_by_id(supabase_client, user_id: str):
    response = supabase_client.table("profiles").select("id, email, first_name, last_name, role").eq("id", user_id).maybe_single().execute()
    if not response or not response.data:
        raise HTTPException(status_code=404, detail="User profile not found")
    return response.data

def parse_pg_array(array_str):
    if not array_str or not isinstance(array_str, str):
        return []
    # Handles quoted and unquoted elements
    return [r[0] or r[1] for r in re.findall(r'"(.*?)"|([^,{}]+)', array_str.strip('{}'))]

def list_users_db(supabase_client):
    response = supabase_client.table("user_profiles_with_login").select("id, email, first_name, last_name, role, last_sign_in_at").execute()
    users = response.data or []
    for user in users:
        role = user.get("role")
        if isinstance(role, str) and role.startswith("{") and role.endswith("}"):
            user["role"] = parse_pg_array(role)
        elif role is None:
            user["role"] = []
        # If already a list, leave as is
    return users

async def invite_user_db(email: str, first_name: str, last_name: str, role: list[str], school_id: str) -> dict:
    """Invite a user via Supabase Auth."""
    try:
        # Create the user metadata
        user_metadata = {
            "first_name": first_name,
            "last_name": last_name,
            "role": role,  # Store the array of roles
            "school_id": school_id
        }

        print("📝 Inviting user with metadata:", user_metadata)

        # Invite the user via Supabase Auth (sync call)
        response = supabase_client.auth.admin.invite_user_by_email(
            email,
            options={
                "data": user_metadata
            }
        )

        if not response or not response.user:
            raise Exception("Failed to create user")

        print("✅ User created successfully:", response.user)

        # Return the user data in a consistent format
        return {
            "id": response.user.id,
            "email": response.user.email,
            "first_name": first_name,
            "last_name": last_name,
            "role": role,
            "school_id": school_id,
            "user_metadata": response.user.user_metadata,
            "app_metadata": response.user.app_metadata
        }
    except Exception as e:
        print(f"❌ Error inviting user: {str(e)}")
        print(f"❌ Error type: {type(e)}")
        print(f"❌ Error details: {e.__dict__ if hasattr(e, '__dict__') else 'No details available'}")
        raise Exception(f"Failed to invite user: {str(e)}")

def update_user_db(supabase_client, user_id, update):
    result = supabase_client.table("profiles").update({
        "first_name": update.first_name,
        "last_name": update.last_name,
        "role": update.role
    }).eq("id", user_id).execute()
    return result

def delete_user_db(supabase_auth, supabase_client, user_id):
    # First delete from profiles table
    profile_result = supabase_client.table("profiles").delete().eq("id", user_id).execute()
    
    # Then delete from auth
    auth_result = supabase_auth.auth.admin.delete_user(user_id)
    
    return {"profile_deleted": profile_result, "auth_deleted": auth_result} 