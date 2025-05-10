from app.services.schools_service import get_school_service

def get_school_controller(school_id):
    return get_school_service(school_id) 