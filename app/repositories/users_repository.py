from fastapi import HTTPException

def get_user_profile_by_id(supabase_client, user_id: str):
    response = supabase_client.table("profiles").select("id, email, first_name, last_name, role").eq("id", user_id).maybe_single().execute()
    if not response or not response.data:
        raise HTTPException(status_code=404, detail="User profile not found")
    return response.data

def list_users_db(supabase_client):
    response = supabase_client.table("profiles").select("id, email, first_name, last_name, role").execute()
    return response.data

def invite_user_db(supabase_auth, email, first_name, last_name, role, school_id):
    result = supabase_auth.auth.admin.invite_user_by_email(
        email,
        {
            "user_metadata": {
                "first_name": first_name,
                "last_name": last_name,
                "role": role,
                "school_id": school_id
            },
            "data": {
                "first_name": first_name,
                "last_name": last_name,
                "role": role,
                "school_id": school_id
            },
            "redirectTo": "http://localhost:3000/accept-invite"
        }
    )
    return result

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