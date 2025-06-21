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

def reset_password_db(supabase_client, email: str):
    """Send password reset email using Supabase"""
    print(f"📧 Sending password reset email to: {email}")
    
    # Get the frontend URL from environment with better defaults
    frontend_url = os.getenv('FRONTEND_URL')
    if not frontend_url:
        # Environment-specific defaults
        if os.getenv('ENVIRONMENT') == 'production':
            frontend_url = 'https://cardcapture.io'
        elif os.getenv('ENVIRONMENT') == 'staging':
            frontend_url = 'https://staging.cardcapture.io'
        else:
            frontend_url = 'http://localhost:3000'
    
    print(f"🔗 Using frontend URL: {frontend_url}")
    
    # Include the reset password page in the redirect URL
    redirect_url = f"{frontend_url}/reset-password"
    print(f"🔗 Redirect URL: {redirect_url}")
    
    try:
        # Use the standard reset_password_for_email method
        response = supabase_client.auth.reset_password_for_email(
            email,
            {"redirect_to": redirect_url}
        )
        
        if hasattr(response, 'error') and response.error:
            print(f"❌ Supabase error: {response.error}")
            raise Exception(f"Failed to send password reset email: {response.error}")
        
        print(f"✅ Password reset email sent to: {email}")
        return response
        
    except Exception as e:
        print(f"❌ Error sending password reset email: {str(e)}")
        raise Exception(f"Error sending password reset email: {str(e)}") 