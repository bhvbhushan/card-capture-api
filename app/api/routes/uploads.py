from fastapi import APIRouter, File, UploadFile, BackgroundTasks, Form, Depends
from fastapi.responses import JSONResponse, FileResponse
from app.controllers.uploads_controller import (
    upload_file_controller,
    check_upload_status_controller,
    get_image_controller,
    export_to_slate_controller
)
from app.core.auth import get_current_user

print("UPLOAD ROUTER FILE:", __file__)
print("MODULE NAME:", __name__)

router = APIRouter(tags=["Uploads"])

@router.post("/upload")
async def upload_file(
    background_tasks: BackgroundTasks,
    file: UploadFile = File(...),
    event_id: str = Form(None),
    school_id: str = Form(...),
    user=Depends(get_current_user)
):
    return await upload_file_controller(background_tasks, file, event_id, school_id, user)

@router.post("/test-upload")
async def test_upload(
    background_tasks: BackgroundTasks,
    file: UploadFile = File(...),
    event_id: str = Form(None),
    school_id: str = Form(...)
):
    # Create a test user object with a valid UUID
    test_user = {
        "id": "00000000-0000-0000-0000-000000000000",
        "email": "test@example.com",
        "role": "admin"
    }
    return await upload_file_controller(background_tasks, file, event_id, school_id, test_user)

@router.get("/upload-status/{document_id}")
async def check_upload_status(document_id: str):
    return await check_upload_status_controller(document_id)

@router.get("/images/{document_id}")
async def get_image(document_id: str):
    return await get_image_controller(document_id)

@router.post("/export-to-slate")
async def export_to_slate(payload: dict):
    return await export_to_slate_controller(payload) 