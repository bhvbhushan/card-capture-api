from fastapi.responses import JSONResponse
from app.repositories.schools_repository import get_school_by_id_db
from app.core.clients import supabase_client

def get_school_service(school_id):
    print(f"🔍 Fetching school with id: {school_id}")
    try:
        school = get_school_by_id_db(supabase_client, school_id)
        print(f"✅ School fetched: {school_id}")
        return {"school": school}
    except Exception as e:
        print(f"❌ Error fetching school: {e}")
        return JSONResponse(status_code=500, content={"error": "Failed to fetch school."}) 