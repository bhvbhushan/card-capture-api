from fastapi.responses import JSONResponse
from fastapi import HTTPException, status
from app.core.clients import supabase_client
from app.repositories.events_repository import (
    insert_event_db,
    update_event_db,
    archive_event_db,
    delete_event_and_cards_db
)
from datetime import datetime, timezone
from app.utils.retry_utils import log_debug

def is_admin(user):
    # Updated to check roles array for admin permission
    user_roles = user.get("role", [])
    return "admin" in user_roles

def has_role(user, role_name):
    """Helper function to check if user has a specific role"""
    user_roles = user.get("role", [])
    return role_name in user_roles

def can_create_events(user):
    """Check if user can create events (admin or recruiter)"""
    user_roles = user.get("role", [])
    return any(role in user_roles for role in ["admin", "recruiter"])

def can_archive_events(user):
    """Check if user can archive events (admin or recruiter)"""
    user_roles = user.get("role", [])
    return any(role in user_roles for role in ["admin", "recruiter"])

async def create_event_service(payload):
    if not supabase_client:
        log_debug("Database client not available", service="events")
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
            log_debug("Failed to create event", service="events")
            return JSONResponse(status_code=500, content={"error": "Failed to create event."})
        log_debug(f"Event created: {response.data[0]}", service="events")
        return JSONResponse(status_code=200, content=response.data[0])
    except Exception as e:
        log_debug(f"Error creating event: {e}", service="events")
        import traceback; traceback.print_exc()
        return JSONResponse(status_code=500, content={"error": "Failed to create event."})

async def update_event_service(event_id: str, payload, user):
    if not is_admin(user):
        log_debug("Only admins can update event names", service="events")
        raise HTTPException(status_code=403, detail="Only admins can update event names.")
    if not supabase_client:
        log_debug("Database client not available", service="events")
        return JSONResponse(status_code=503, content={"error": "Database client not available."})
    try:
        result = update_event_db(supabase_client, event_id, {"name": payload.name})
        if hasattr(result, 'error') and result.error:
            log_debug(f"Error updating event {event_id}: {result.error}", service="events")
            raise Exception(result.error)
        log_debug(f"Event updated: {event_id}", service="events")
        return {"success": True}
    except Exception as e:
        log_debug(f"Error updating event {event_id}: {e}", service="events")
        return JSONResponse(status_code=500, content={"error": str(e)})

async def archive_events_service(payload):
    if not supabase_client:
        log_debug("Database client not available", service="events")
        return JSONResponse(status_code=503, content={"error": "Database client not available."})
    try:
        archived_count = 0
        errors = []
        
        # Archive each event individually
        for event_id in payload.event_ids:
            try:
                result = archive_event_db(supabase_client, event_id, "system", "Bulk archive operation")
                archived_count += 1
                log_debug(f"Successfully archived event {event_id}", service="events")
            except Exception as e:
                error_msg = f"Failed to archive event {event_id}: {str(e)}"
                errors.append(error_msg)
                log_debug(f"{error_msg}", service="events")
        
        if archived_count == len(payload.event_ids):
            return JSONResponse(
                status_code=200,
                content={"message": f"Successfully archived {archived_count} events"}
            )
        elif archived_count > 0:
            return JSONResponse(
                status_code=207,  # Multi-status
                content={
                    "message": f"Archived {archived_count} out of {len(payload.event_ids)} events",
                    "errors": errors
                }
            )
        else:
            return JSONResponse(
                status_code=500,
                content={
                    "message": "Failed to archive any events",
                    "errors": errors
                }
            )
    except Exception as e:
        log_debug(f"Error archiving events: {e}", service="events")
        import traceback; traceback.print_exc()
        return JSONResponse(
            status_code=500,
            content={"error": str(e)}
        )

async def delete_event_service(event_id: str, user):
    if not is_admin(user):
        log_debug("Only admins can delete events", service="events")
        raise HTTPException(status_code=403, detail="Only admins can delete events.")
    if not supabase_client:
        log_debug("Database client not available", service="events")
        return JSONResponse(status_code=503, content={"error": "Database client not available."})
    try:
        reviewed, extracted, event = delete_event_and_cards_db(supabase_client, event_id)
        log_debug(f"Deleted event {event_id} and associated cards", service="events")
        return JSONResponse(status_code=status.HTTP_204_NO_CONTENT, content={"success": True})
    except Exception as e:
        log_debug(f"Error deleting event {event_id}: {e}", service="events")
        return JSONResponse(status_code=500, content={"error": str(e)}) 