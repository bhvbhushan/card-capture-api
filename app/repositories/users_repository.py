from fastapi import HTTPException
from app.core.clients import supabase_client
import re
from typing import List
import os

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
    """Invite a new user to the system"""
    print(f"📧 Inviting user: {email} to school: {school_id}")
    
    # Prepare user metadata
    user_metadata = {
        "first_name": first_name,
        "last_name": last_name,
        "role": role,
        "school_id": school_id,
        "email_verified": False
    }
    
    try:
        # Get the frontend URL from environment or use default
        frontend_url = os.getenv('FRONTEND_URL', 'http://localhost:3000')
        redirect_url = f"{frontend_url}/accept-invite"
        
        # Use invite_user_by_email to send the invitation email
        response = supabase_client.auth.admin.invite_user_by_email(
            email,
            options={
                "data": user_metadata,  # This adds the metadata to the user
                "redirect_to": redirect_url  # Where they go after clicking the link
            }
        )
        
        if hasattr(response, 'error') and response.error:
            print(f"❌ Supabase error: {response.error}")
            raise Exception(f"Failed to invite user: {response.error}")
        
        # After invite, we need to update app_metadata separately if needed
        if response and response.user:
            print(f"🔄 Creating user profile and metadata for {response.user.id}")
            
            # Update app_metadata
            supabase_client.auth.admin.update_user_by_id(
                response.user.id,
                {
                    "app_metadata": {
                        "school_id": school_id
                    }
                }
            )
            
            # Create profile record in the profiles table
            profile_data = {
                "id": response.user.id,
                "email": email,
                "first_name": first_name,
                "last_name": last_name,
                "role": role,
                "school_id": school_id
            }
            
            # Use upsert to handle potential conflicts
            supabase_client.table("profiles").upsert(profile_data).execute()
            print(f"✅ User profile created successfully")
        
        # Format the return value properly
        user_data = {
            "id": response.user.id,
            "email": response.user.email,
            "first_name": first_name,
            "last_name": last_name,
            "role": role,
            "school_id": school_id,
            "created_at": str(response.user.created_at),
            "email_confirmed": response.user.email_confirmed_at is not None,
            "invite_sent": True
        }
            
        print(f"✅ Invitation email sent to: {email}")
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