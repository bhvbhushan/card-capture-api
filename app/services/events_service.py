from fastapi.responses import JSONResponse
from fastapi import HTTPException, status
from app.core.clients import supabase_client
from app.repositories.events_repository import (
    insert_event_db,
    update_event_db,
    archive_events_db,
    delete_event_and_cards_db
)
from datetime import datetime, timezone

def is_admin(user):
    return user.get("role") == "admin"

async def create_event_service(payload):
    if not supabase_client:
        print("❌ Database client not available")
        return JSONResponse(status_code=503, content={"error": "Database client not available."})
    try:
        event_data = {
            "name": payload.name,
            "date": payload.date,
            "school_id": payload.school_id,
            "status": "active"
        }
        response = insert_event_db(supabase_client, event_data)
        if not response.data:
            print("❌ Failed to create event.")
            return JSONResponse(status_code=500, content={"error": "Failed to create event."})
        print(f"✅ Event created: {response.data[0]}")
        return JSONResponse(status_code=200, content=response.data[0])
    except Exception as e:
        print(f"❌ Error creating event: {e}")
        import traceback; traceback.print_exc()
        return JSONResponse(status_code=500, content={"error": "Failed to create event."})

async def update_event_service(event_id: str, payload, user):
    if not is_admin(user):
        print("❌ Only admins can update event names.")
        raise HTTPException(status_code=403, detail="Only admins can update event names.")
    if not supabase_client:
        print("❌ Database client not available")
        return JSONResponse(status_code=503, content={"error": "Database client not available."})
    try:
        result = update_event_db(supabase_client, event_id, {"name": payload.name})
        if hasattr(result, 'error') and result.error:
            print(f"❌ Error updating event {event_id}: {result.error}")
            raise Exception(result.error)
        print(f"✅ Event updated: {event_id}")
        return {"success": True}
    except Exception as e:
        print(f"❌ Error updating event {event_id}: {e}")
        return JSONResponse(status_code=500, content={"error": str(e)})

async def archive_events_service(payload):
    if not supabase_client:
        print("❌ Database client not available")
        return JSONResponse(status_code=503, content={"error": "Database client not available."})
    try:
        result = archive_events_db(supabase_client, payload.event_ids)
        print(f"✅ Successfully archived {len(payload.event_ids)} events")
        return JSONResponse(
            status_code=200,
            content={"message": f"Successfully archived {len(payload.event_ids)} events"}
        )
    except Exception as e:
        print(f"❌ Error archiving events: {e}")
        import traceback; traceback.print_exc()
        return JSONResponse(
            status_code=500,
            content={"error": str(e)}
        )

async def delete_event_service(event_id: str, user):
    if not is_admin(user):
        print("❌ Only admins can delete events.")
        raise HTTPException(status_code=403, detail="Only admins can delete events.")
    if not supabase_client:
        print("❌ Database client not available")
        return JSONResponse(status_code=503, content={"error": "Database client not available."})
    try:
        reviewed, extracted, event = delete_event_and_cards_db(supabase_client, event_id)
        print(f"✅ Deleted event {event_id} and associated cards.")
        return JSONResponse(status_code=status.HTTP_204_NO_CONTENT, content={"success": True})
    except Exception as e:
        print(f"❌ Error deleting event {event_id}: {e}")
        return JSONResponse(status_code=500, content={"error": str(e)}) 