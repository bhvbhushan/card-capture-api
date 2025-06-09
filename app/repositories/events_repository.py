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

@safe_db_operation("Create event")
def create_event_db(
    supabase_client,
    event_data: Dict[str, Any],
    created_by: str
):
    """
    Create a new event - simplified to only use existing tables.
    """
    timestamp = datetime.now(timezone.utc).isoformat()
    
    # Create event - only use columns that exist
    event_data.update({
        "created_at": timestamp,
        "updated_at": timestamp
    })
    
    return supabase_client.table("events").insert(event_data).execute()

@safe_db_operation("Update event")
def update_event_db(
    supabase_client,
    event_id: str,
    event_data: Dict[str, Any]
):
    """
    Update an event - simplified to only use existing tables.
    """
    timestamp = datetime.now(timezone.utc).isoformat()
    
    # Update event - only use columns that exist
    event_data["updated_at"] = timestamp
    
    return supabase_client.table("events").update(event_data).eq("id", event_id).execute()

@safe_db_operation("Archive event")
def archive_event_db(supabase_client, event_id: str):
    """
    Archive an event - simplified to only use existing columns.
    """
    timestamp = datetime.now(timezone.utc).isoformat()
    
    # Update event status - only use columns that exist in events table
    event_response = supabase_client.table("events").update({
        "status": "archived",
        "updated_at": timestamp
    }).eq("id", event_id).execute()
    
    # Archive reviewed data - only use columns that exist in reviewed_data table  
    data_response = supabase_client.table("reviewed_data").update({
        "review_status": "archived",
        "updated_at": timestamp
    }).eq("event_id", event_id).execute()
    
    return {
        "event": event_response,
        "reviewed_data": data_response
    }

@safe_db_operation("Update event metrics")
def update_event_metrics_db(
    supabase_client,
    event_id: str,
    updated_by: str
):
    """
    Update event metrics - simplified to only update events table.
    """
    timestamp = datetime.now(timezone.utc).isoformat()
    
    # Update event with timestamp
    return supabase_client.table("events").update({
        "updated_at": timestamp
    }).eq("id", event_id).execute()

def delete_event_and_cards_db(supabase_client, event_id: str):
    reviewed = supabase_client.table("reviewed_data").delete().eq("event_id", event_id).execute()
    extracted = supabase_client.table("extracted_data").delete().eq("event_id", event_id).execute()
    event = supabase_client.table("events").delete().eq("id", event_id).execute()
    return reviewed, extracted, event 