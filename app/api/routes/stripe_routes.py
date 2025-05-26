from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import JSONResponse
import os
from app.core.auth import get_current_user
from app.core.clients import supabase_client

router = APIRouter(prefix="/stripe", tags=["Stripe"])

@router.post("/create-portal-session")
async def create_portal_session(user=Depends(get_current_user)):
    """
    Create a Stripe customer portal session for the user's school
    """
    try:
        # Check if Stripe is available
        try:
            import stripe
        except ImportError as e:
            print(f"Stripe import error: {e}")
            raise HTTPException(status_code=500, detail="Stripe library not installed")
        
        # Configure Stripe
        stripe_secret_key = os.getenv("STRIPE_SECRET_KEY")
        print(f"Stripe secret key configured: {bool(stripe_secret_key)}")
        
        if not stripe_secret_key:
            print("STRIPE_SECRET_KEY environment variable not found")
            raise HTTPException(status_code=500, detail="Stripe not configured")
        
        stripe.api_key = stripe_secret_key
        
        # Get the user's school information
        print(f"User data: {user}")
        if not user or not user.get("school_id"):
            print("User school not found")
            raise HTTPException(status_code=400, detail="User school not found")
        
        school_id = user.get("school_id")
        print(f"School ID: {school_id}")
        
        # Fetch school record to get stripe_customer_id
        school_response = supabase_client.table("schools").select("stripe_customer_id, name").eq("id", school_id).single().execute()
        
        print(f"School response: {school_response.data}")
        if not school_response.data:
            raise HTTPException(status_code=404, detail="School not found")
        
        school = school_response.data
        stripe_customer_id = school.get("stripe_customer_id")
        print(f"Stripe customer ID: {stripe_customer_id}")
        
        if not stripe_customer_id:
            raise HTTPException(status_code=400, detail="No Stripe customer ID found for this school. Please contact support.")
        
        # Create the portal session
        print("Creating Stripe portal session...")
        
        # You can optionally specify a configuration ID if you have multiple portal configurations
        # configuration = "bpc_xxxxx"  # Replace with your actual configuration ID if needed
        
        session = stripe.billing_portal.Session.create(
            customer=stripe_customer_id,
            return_url=os.getenv("FRONTEND_URL", "http://localhost:3000") + "/settings/subscription",
            # configuration=configuration,  # Uncomment and set if you want to use a specific configuration
        )
        
        print(f"Portal session created: {session.url}")
        return JSONResponse(status_code=200, content={"url": session.url})
        
    except stripe.error.StripeError as e:
        print(f"Stripe error: {e}")
        raise HTTPException(status_code=400, detail=f"Stripe error: {str(e)}")
    except Exception as e:
        print(f"Error creating portal session: {e}")
        import traceback
        traceback.print_exc()
        raise HTTPException(status_code=500, detail="Failed to create billing portal session") 