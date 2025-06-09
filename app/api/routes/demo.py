from fastapi import APIRouter
from app.models.demo import DemoRequest
from app.controllers.demo_controller import send_demo_request_controller

router = APIRouter(prefix="/demo", tags=["Demo"])

@router.post("/send-request")
async def send_demo_request(demo_request: DemoRequest):
    """Send a demo request email"""
    return await send_demo_request_controller(demo_request) 