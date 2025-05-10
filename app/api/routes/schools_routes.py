from fastapi import APIRouter, Depends
from app.controllers.schools_controller import get_school_controller
from app.core.auth import get_current_user

router = APIRouter(tags=["Schools"])

@router.get("/schools/{school_id}")
async def get_school(school_id: str, user=Depends(get_current_user)):
    return get_school_controller(school_id) 