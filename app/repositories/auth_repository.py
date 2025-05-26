from fastapi import HTTPException
import os
from jose import jwt, JWTError

def login_db(supabase_auth, credentials: dict):
    print("🔐 Login attempt for:", credentials.get("email"))
    response = supabase_auth.auth.sign_in_with_password({
        "email": credentials.get("email"),
        "password": credentials.get("password")
    })
    print("✅ Login successful")
    return response

def get_user_profile_db(supabase_client, user_id: str):
    response = supabase_client.table("profiles").select("id, email, first_name, last_name, role, school_id").eq("id", user_id).maybe_single().execute()
    if not response or not response.data:
        raise HTTPException(status_code=404, detail="User profile not found")
    return response.data 