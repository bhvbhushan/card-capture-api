from fastapi import Request, HTTPException
from app.core.clients import supabase_auth, supabase_client
import os
from jose import jwt, JWTError
from app.repositories.auth_repository import login_db, get_user_profile_db, reset_password_db
from app.utils.retry_utils import log_debug

async def login_service(credentials: dict):
    try:
        log_debug("Login attempt for:", credentials.get("email"), service="auth")
        response = login_db(supabase_auth, credentials)
        log_debug("Login successful", service="auth")
        return response
    except Exception as e:
        log_debug("Login error:", str(e), service="auth")
        raise HTTPException(status_code=401, detail="Invalid credentials")

async def read_current_user_service(request: Request):
    try:
        auth_header = request.headers.get("Authorization")
        if not auth_header or not auth_header.startswith("Bearer "):
            log_debug("Missing or invalid Authorization header", service="auth")
            raise HTTPException(status_code=401, detail="Missing or invalid Authorization header")
        
        token = auth_header.split(" ")[1]
        
        # Get user from token
        user_response = supabase_client.auth.get_user(token)
        if not user_response.user:
            raise HTTPException(status_code=401, detail="Invalid or expired token")
        
        user_id = user_response.user.id
        if not user_id:
            log_debug("User ID not found in token", service="auth")
            raise HTTPException(status_code=401, detail="User ID not found in token")
        
        log_debug(f"Fetching user profile for user_id: {user_id}", service="auth")
        profile_response = supabase_client.table("users").select("*").eq("id", user_id).execute()
        log_debug(f"User profile fetched for user_id: {user_id}", service="auth")
        
        return profile_response.data[0] if profile_response.data else None
        
    except HTTPException:
        log_debug("Invalid or expired token", service="auth")
        raise
    except Exception as e:
        log_debug(f"Error fetching user profile: {e}", service="auth")
        raise HTTPException(status_code=500, detail="Internal server error")

async def reset_password_service(payload: dict):
    try:
        email = payload.get("email")
        if not email:
            raise HTTPException(status_code=400, detail="Email is required")
        
        log_debug(f"Password reset request for: {email}", service="auth")
        response = reset_password_db(supabase_client, email)
        log_debug(f"Password reset email sent to: {email}", service="auth")
        return {"message": "Password reset email sent successfully"}
    except HTTPException:
        raise
    except Exception as e:
        log_debug(f"Password reset error: {str(e)}", service="auth")
        raise HTTPException(status_code=500, detail="Failed to send password reset email") 