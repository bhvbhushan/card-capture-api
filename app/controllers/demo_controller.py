from app.models.demo import DemoRequest
from app.services.demo_service import send_demo_request_service

async def send_demo_request_controller(demo_request: DemoRequest):
    """Controller for handling demo request submissions"""
    return await send_demo_request_service(demo_request) 