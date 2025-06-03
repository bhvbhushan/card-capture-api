from app.services.schools_service import get_school_service

async def get_school_controller(school_id):
    return await get_school_service(school_id) 