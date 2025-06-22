from fastapi import HTTPException
from app.core.clients import supabase_client
import re
from typing import List
import os
from datetime import datetime

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

def invite_user_db(email: str, first_name: str, last_name: str, role: List[str], school_id: str):
    """Invite a new user to the system using magic links"""
    print(f"📧 Inviting user: {email} to school: {school_id}")
    
    # Import magic link function
    from app.repositories.auth_repository import send_magic_link_email_db
    
    # Prepare user metadata for magic link
    user_metadata = {
        "first_name": first_name,
        "last_name": last_name,
        "role": role,
        "school_id": school_id,
        "email_verified": False
    }
    
    try:
        # Send magic link email for invite
        magic_link_response = send_magic_link_email_db(
            supabase_client, 
            email, 
            "invite", 
            user_metadata
        )
        
        if not magic_link_response.get("success"):
            raise Exception("Failed to send magic link invite email")
        
        # Check if user already exists in Supabase auth
        user_response = supabase_client.auth.admin.list_users()
        existing_user = None
        
        for u in user_response:
            if u.email == email:
                existing_user = u
                break
        
        # If user doesn't exist yet, create a placeholder response
        if not existing_user:
            # Create a temporary user record for tracking
            # We'll create the actual user when they click the magic link
            user_data = {
                "id": f"pending-{email.replace('@', '-at-').replace('.', '-dot-')}",
                "email": email,
                "first_name": first_name,
                "last_name": last_name,
                "role": role,
                "school_id": school_id,
                "created_at": str(datetime.utcnow()),
                "email_confirmed": False,
                "invite_sent": True,
                "status": "pending_magic_link"
            }
        else:
            # User exists, update their profile
            print(f"🔄 Updating existing user profile for {existing_user.id}")
            
            # Update app_metadata
            supabase_client.auth.admin.update_user_by_id(
                existing_user.id,
                {
                    "app_metadata": {
                        "school_id": school_id
                    }
                }
            )
            
            # Create/update profile record in the profiles table
            profile_data = {
                "id": existing_user.id,
                "email": email,
                "first_name": first_name,
                "last_name": last_name,
                "role": role,
                "school_id": school_id
            }
            
            # Use upsert to handle potential conflicts
            supabase_client.table("profiles").upsert(profile_data).execute()
            print(f"✅ User profile updated successfully")
            
            # Format the return value properly
            user_data = {
                "id": existing_user.id,
                "email": existing_user.email,
                "first_name": first_name,
                "last_name": last_name,
                "role": role,
                "school_id": school_id,
                "created_at": str(existing_user.created_at),
                "email_confirmed": existing_user.email_confirmed_at is not None,
                "invite_sent": True,
                "magic_link_token": magic_link_response.get("token", "")[:8] + "..."
            }
            
        print(f"✅ Magic link invitation sent to: {email}")
        return user_data
        
    except Exception as e:
        print(f"❌ Error inviting user: {str(e)}")
        import traceback
        print(f"❌ Stack trace: {traceback.format_exc()}")
        raise Exception(f"Error inviting user: {str(e)}")

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