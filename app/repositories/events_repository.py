from datetime import datetime, timezone
from typing import Dict, Any, List, Optional
from fastapi import HTTPException
from app.utils.db_utils import (
    ensure_atomic_updates,
    safe_db_operation,
    validate_db_response,
    handle_db_error
)

def insert_event_db(supabase_client, event_data: Dict[str, Any]):
    return supabase_client.table("events").insert(event_data).execute()

@safe_db_operation("Get event")
def get_event_db(supabase_client, event_id: str):
    """Get event details with proper error handling."""
    return supabase_client.table("events").select("*").eq("id", event_id).single().execute()

@safe_db_operation("Get school events")
def get_school_events_db(supabase_client, school_id: str):
    """Get all events for a school with proper error handling."""
    return supabase_client.table("events").select("*").eq("school_id", school_id).execute()

@ensure_atomic_updates(["events", "event_history", "event_staff"])
def create_event_db(
    supabase_client,
    event_data: Dict[str, Any],
    staff_assignments: List[Dict[str, Any]],
    created_by: str
):
    """
    Create a new event with history tracking and staff assignments atomically.
    If any operation fails, all are rolled back.
    """
    try:
        timestamp = datetime.now(timezone.utc).isoformat()
        
        # Create event record
        event_response = supabase_client.table("events").insert({
            **event_data,
            "created_at": timestamp,
            "updated_at": timestamp,
            "created_by": created_by
        }).execute()
        
        if not validate_db_response(event_response, "Create event"):
            raise HTTPException(status_code=500, detail="Failed to create event")
            
        event_id = event_response.data[0]["id"]
        
        # Create event history record
        history_record = {
            "event_id": event_id,
            "action": "create",
            "action_by": created_by,
            "timestamp": timestamp,
            "changes": event_data,
            "metadata": {
                "source": "user_action",
                "details": "Event created"
            }
        }
        
        history_response = supabase_client.table("event_history").insert(history_record).execute()
        if not validate_db_response(history_response, "Create event history"):
            raise HTTPException(status_code=500, detail="Failed to create event history")
            
        # Create staff assignments if provided
        if staff_assignments:
            staff_records = [{
                "event_id": event_id,
                "user_id": assignment["user_id"],
                "role": assignment["role"],
                "assigned_at": timestamp,
                "assigned_by": created_by
            } for assignment in staff_assignments]
            
            staff_response = supabase_client.table("event_staff").insert(staff_records).execute()
            if not validate_db_response(staff_response, "Create staff assignments"):
                raise HTTPException(status_code=500, detail="Failed to create staff assignments")
        
        return {
            "event": event_response.data[0],
            "history": history_response.data[0],
            "staff": staff_response.data if staff_assignments else None
        }
        
    except Exception as e:
        error_details = handle_db_error(e, "Create event")
        raise HTTPException(status_code=500, detail=error_details)

@ensure_atomic_updates(["events", "event_history", "event_staff"])
def update_event_db(
    supabase_client,
    event_id: str,
    event_data: Dict[str, Any],
    staff_changes: Optional[Dict[str, List[Dict[str, Any]]]] = None,
    updated_by: str = None
):
    """
    Update event details with history tracking and staff changes atomically.
    If any operation fails, all are rolled back.
    
    Args:
        event_id: The ID of the event to update
        event_data: New event data
        staff_changes: Optional dict with 'add' and 'remove' lists for staff changes
        updated_by: User ID making the update
    """
    try:
        timestamp = datetime.now(timezone.utc).isoformat()
        
        # Get current event data for change tracking
        current_event = supabase_client.table("events").select("*").eq("id", event_id).single().execute()
        if not current_event.data:
            raise HTTPException(status_code=404, detail="Event not found")
            
        # Update event
        event_response = supabase_client.table("events").update({
            **event_data,
            "updated_at": timestamp,
            "last_updated_by": updated_by
        }).eq("id", event_id).execute()
        
        if not validate_db_response(event_response, "Update event"):
            raise HTTPException(status_code=500, detail="Failed to update event")
            
        # Create history record with detailed changes
        changes = {
            field: {
                "old": current_event.data.get(field),
                "new": event_data.get(field)
            }
            for field in event_data.keys()
            if current_event.data.get(field) != event_data.get(field)
        }
        
        history_record = {
            "event_id": event_id,
            "action": "update",
            "action_by": updated_by,
            "timestamp": timestamp,
            "changes": changes,
            "metadata": {
                "source": "user_action",
                "details": "Event details updated"
            }
        }
        
        history_response = supabase_client.table("event_history").insert(history_record).execute()
        if not validate_db_response(history_response, "Create update history"):
            raise HTTPException(status_code=500, detail="Failed to create update history")
            
        # Handle staff changes if provided
        staff_updates = None
        if staff_changes:
            staff_updates = {}
            
            # Add new staff
            if staff_changes.get("add"):
                add_records = [{
                    "event_id": event_id,
                    "user_id": staff["user_id"],
                    "role": staff["role"],
                    "assigned_at": timestamp,
                    "assigned_by": updated_by
                } for staff in staff_changes["add"]]
                
                add_response = supabase_client.table("event_staff").insert(add_records).execute()
                if not validate_db_response(add_response, "Add staff"):
                    raise HTTPException(status_code=500, detail="Failed to add staff")
                staff_updates["added"] = add_response.data
                
            # Remove staff
            if staff_changes.get("remove"):
                remove_user_ids = [staff["user_id"] for staff in staff_changes["remove"]]
                remove_response = supabase_client.table("event_staff").delete().eq("event_id", event_id).in_("user_id", remove_user_ids).execute()
                if not validate_db_response(remove_response, "Remove staff"):
                    raise HTTPException(status_code=500, detail="Failed to remove staff")
                staff_updates["removed"] = remove_response.data
                
            # Create staff change history
            staff_history = {
                "event_id": event_id,
                "action": "staff_update",
                "action_by": updated_by,
                "timestamp": timestamp,
                "changes": staff_changes,
                "metadata": {
                    "source": "user_action",
                    "details": "Staff assignments updated"
                }
            }
            
            staff_history_response = supabase_client.table("event_history").insert(staff_history).execute()
            if not validate_db_response(staff_history_response, "Create staff update history"):
                raise HTTPException(status_code=500, detail="Failed to create staff update history")
        
        return {
            "event": event_response.data[0],
            "history": [history_response.data[0]],
            "staff_updates": staff_updates
        }
        
    except Exception as e:
        error_details = handle_db_error(e, "Update event")
        raise HTTPException(status_code=500, detail=error_details)

@ensure_atomic_updates(["events", "event_history", "event_staff", "reviewed_data"])
def archive_event_db(supabase_client, event_id: str, archived_by: str, archive_reason: str = None):
    """
    Archive an event and all its data atomically.
    Updates event status, creates history, archives staff assignments and reviewed data.
    """
    try:
        timestamp = datetime.now(timezone.utc).isoformat()
        
        # Update event status
        event_response = supabase_client.table("events").update({
            "status": "archived",
            "archived_at": timestamp,
            "archived_by": archived_by,
            "archive_reason": archive_reason,
            "updated_at": timestamp
        }).eq("id", event_id).execute()
        
        if not validate_db_response(event_response, "Archive event"):
            raise HTTPException(status_code=500, detail="Failed to archive event")
            
        # Create archive history record
        history_record = {
            "event_id": event_id,
            "action": "archive",
            "action_by": archived_by,
            "timestamp": timestamp,
            "changes": {"status": "archived"},
            "metadata": {
                "source": "user_action",
                "reason": archive_reason,
                "details": "Event archived"
            }
        }
        
        history_response = supabase_client.table("event_history").insert(history_record).execute()
        if not validate_db_response(history_response, "Create archive history"):
            raise HTTPException(status_code=500, detail="Failed to create archive history")
            
        # Archive staff assignments
        staff_response = supabase_client.table("event_staff").update({
            "status": "archived",
            "archived_at": timestamp
        }).eq("event_id", event_id).execute()
        
        # Archive reviewed data
        data_response = supabase_client.table("reviewed_data").update({
            "event_archived": True,
            "event_archived_at": timestamp
        }).eq("event_id", event_id).execute()
        
        return {
            "event": event_response.data[0],
            "history": history_response.data[0],
            "staff": staff_response.data,
            "reviewed_data": data_response.data
        }
        
    except Exception as e:
        error_details = handle_db_error(e, "Archive event")
        raise HTTPException(status_code=500, detail=error_details)

@ensure_atomic_updates(["events", "event_history", "event_metrics"])
def update_event_metrics_db(
    supabase_client,
    event_id: str,
    metrics: Dict[str, Any],
    updated_by: str
):
    """
    Update event metrics with history tracking atomically.
    """
    try:
        timestamp = datetime.now(timezone.utc).isoformat()
        
        # Get current metrics for change tracking
        current_metrics = supabase_client.table("event_metrics").select("*").eq("event_id", event_id).single().execute()
        
        # Update or create metrics
        metrics_data = {
            "event_id": event_id,
            **metrics,
            "updated_at": timestamp,
            "updated_by": updated_by
        }
        
        if current_metrics.data:
            metrics_response = supabase_client.table("event_metrics").update(metrics_data).eq("event_id", event_id).execute()
        else:
            metrics_response = supabase_client.table("event_metrics").insert(metrics_data).execute()
            
        if not validate_db_response(metrics_response, "Update metrics"):
            raise HTTPException(status_code=500, detail="Failed to update metrics")
            
        # Create metrics history record
        history_record = {
            "event_id": event_id,
            "action": "metrics_update",
            "action_by": updated_by,
            "timestamp": timestamp,
            "changes": {
                "old_metrics": current_metrics.data,
                "new_metrics": metrics
            },
            "metadata": {
                "source": "system",
                "details": "Event metrics updated"
            }
        }
        
        history_response = supabase_client.table("event_history").insert(history_record).execute()
        
        # Update event last_metrics_update
        event_response = supabase_client.table("events").update({
            "last_metrics_update": timestamp
        }).eq("id", event_id).execute()
        
        return {
            "metrics": metrics_response.data[0],
            "history": history_response.data[0],
            "event": event_response.data[0]
        }
        
    except Exception as e:
        error_details = handle_db_error(e, "Update event metrics")
        raise HTTPException(status_code=500, detail=error_details)

def delete_event_and_cards_db(supabase_client, event_id: str):
    reviewed = supabase_client.table("reviewed_data").delete().eq("event_id", event_id).execute()
    extracted = supabase_client.table("extracted_data").delete().eq("event_id", event_id).execute()
    event = supabase_client.table("events").delete().eq("id", event_id).execute()
    return reviewed, extracted, event 