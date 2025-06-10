import os
import resend
from fastapi import HTTPException
from app.models.demo import DemoRequest
from app.utils.retry_utils import log_debug

async def send_demo_request_service(demo_request: DemoRequest):
    """Send a demo request email using Resend"""
    try:
        log_debug("Processing demo request", {"email": demo_request.email, "university": demo_request.university}, service="demo")
        
        # Initialize Resend with API key from environment
        resend_api_key = os.getenv("RESEND_API_KEY")
        if not resend_api_key:
            log_debug("RESEND_API_KEY not found in environment variables", service="demo")
            raise HTTPException(status_code=500, detail="Email service not configured")
        
        # Set the API key for resend
        resend.api_key = resend_api_key
        
        # Create HTML email content
        html_content = f"""
        <h2>New Demo Request</h2>
        <p><strong>Name:</strong> {demo_request.name}</p>
        <p><strong>Email:</strong> {demo_request.email}</p>
        <p><strong>University:</strong> {demo_request.university}</p>
        <p><strong>Enrollment:</strong> {demo_request.enrollment or 'Not provided'}</p>
        <p><strong>Message:</strong> {demo_request.message or 'No additional message'}</p>
        <hr>
        <p><em>This demo request was submitted through the Card Capture website.</em></p>
        """
        
        # Prepare email parameters according to Resend API
        params: resend.Emails.SendParams = {
            "from": "Card Capture Demo <no-reply@cardcapture.io>",
            "to": ["demo@cardcapture.io"],
            "subject": f"New Demo Request from {demo_request.university}",
            "html": html_content
        }
        
        # Send email using Resend
        email_response = resend.Emails.send(params)
        
        log_debug("Demo request email sent successfully", {"email_id": email_response.get("id")}, service="demo")
        
        return {
            "success": True,
            "message": "Demo request sent successfully",
            "email_id": email_response.get("id")
        }
        
    except Exception as e:
        log_debug(f"Error sending demo request email: {str(e)}", service="demo")
        raise HTTPException(status_code=500, detail=f"Failed to send demo request: {str(e)}") 