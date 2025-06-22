from fastapi import Request, HTTPException
from app.core.clients import supabase_auth, supabase_client
import os
from jose import jwt, JWTError
from app.repositories.auth_repository import (
    login_db, 
    get_user_profile_db, 
    reset_password_db,
    validate_magic_link_db,
    consume_magic_link_db,
    create_temporary_session_db
)
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

async def validate_magic_link_service(token: str):
    """Validate a magic link token"""
    try:
        log_debug(f"Validating magic link token: {token[:8]}...", service="auth")
        
        magic_link = validate_magic_link_db(supabase_client, token)
        
        if not magic_link:
            raise HTTPException(status_code=400, detail="Invalid or expired magic link")
        
        log_debug(f"Magic link validated for: {magic_link['email']}", service="auth")
        return magic_link
        
    except HTTPException:
        raise
    except Exception as e:
        log_debug(f"Magic link validation error: {str(e)}", service="auth")
        raise HTTPException(status_code=500, detail="Failed to validate magic link")

async def consume_magic_link_service(token: str, link_type: str):
    """Process a magic link after validation"""
    try:
        log_debug(f"Processing magic link: {token[:8]}... (type: {link_type})", service="auth")
        
        # First validate the magic link
        magic_link = validate_magic_link_db(supabase_client, token)
        
        if not magic_link:
            raise HTTPException(status_code=400, detail="Invalid or expired magic link")
        
        if magic_link['type'] != link_type:
            raise HTTPException(status_code=400, detail="Magic link type mismatch")
        
        email = magic_link['email']
        metadata = magic_link['metadata']
        
        # Process based on link type
        if link_type == "password_reset":
            # For password reset, we'll let the frontend handle the authentication
            # Mark magic link as consumed
            consume_magic_link_db(supabase_client, token)
            
            log_debug(f"Password reset magic link processed for: {email}", service="auth")
            return {
                "type": "password_reset",
                "email": email,
                "redirect_url": "/reset-password",
                "success": True
            }
            
        elif link_type == "invite":
            # Simple invite handling - just validate and return metadata
            log_debug(f"Processing invite magic link for: {email}", service="auth")
            
            # Mark magic link as consumed
            consume_magic_link_db(supabase_client, token)
            
            log_debug(f"Invite magic link processed for: {email}", service="auth")
            return {
                "type": "invite",
                "email": email,
                "redirect_url": "/accept-invite",
                "metadata": metadata,
                "success": True
            }
        
        else:
            raise HTTPException(status_code=400, detail="Unknown magic link type")
            
    except HTTPException:
        raise
    except Exception as e:
        log_debug(f"Magic link processing error: {str(e)}", service="auth")
        raise HTTPException(status_code=500, detail="Failed to process magic link")

async def create_user_service(payload: dict):
    """Create a new user account for invite flow"""
    try:
        email = payload.get("email")
        password = payload.get("password")
        first_name = payload.get("first_name", "")
        last_name = payload.get("last_name", "")
        role = payload.get("role", [])
        school_id = payload.get("school_id", "")
        
        if not email or not password:
            raise HTTPException(status_code=400, detail="Email and password are required")
        
        log_debug(f"Creating user account for: {email}", service="auth")
        
        # Create user with their actual password (simplified approach)
        try:
            create_response = supabase_client.auth.admin.create_user({
                "email": email,
                "password": password,
                "email_confirm": True  # Auto-confirm since they came from magic link
            })
            
            if not create_response.user:
                raise HTTPException(status_code=500, detail="Failed to create user account")
            
            user_id = create_response.user.id
            log_debug(f"User created successfully: {user_id}", service="auth")
            
        except Exception as create_error:
            log_debug(f"User creation error: {str(create_error)}", service="auth")
            raise HTTPException(status_code=500, detail=f"Failed to create user: {str(create_error)}")
        
        # Try to create profile record (non-critical)
        try:
            profile_data = {
                "id": user_id,
                "email": email,
                "first_name": first_name,
                "last_name": last_name,
                "role": role,
                "school_id": school_id
            }
            
            supabase_client.table("profiles").upsert(profile_data).execute()
            log_debug(f"Profile created for: {email}", service="auth")
        except Exception as profile_error:
            log_debug(f"Profile creation error (non-fatal): {str(profile_error)}", service="auth")
            # Don't fail the whole process for profile errors
        
        log_debug(f"User account created successfully for: {email}", service="auth")
        return {
            "success": True,
            "user_id": user_id,
            "email": email,
            "message": "User account created successfully"
        }
        
    except HTTPException:
        raise
    except Exception as e:
        log_debug(f"User creation error: {str(e)}", service="auth")
        raise HTTPException(status_code=500, detail="Failed to create user account") 