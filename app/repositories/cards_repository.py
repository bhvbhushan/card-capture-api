from typing import List, Dict, Any, Union
from datetime import datetime, timezone
from app.utils.archive_logging import log_archive_debug
from app.utils.db_utils import (
    ensure_atomic_updates,
    safe_db_operation,
    validate_db_response,
    handle_db_error
)
from fastapi import HTTPException

@safe_db_operation("Get cards")
def get_cards_db(supabase_client, event_id: Union[str, None] = None) -> List[Dict[str, Any]]:
    """Get cards with proper error handling."""
    query = supabase_client.table("reviewed_data").select("*")
    if event_id:
        query = query.eq("event_id", event_id)
    response = query.execute()
    
    if not validate_db_response(response, "Get cards"):
        return []
        
    filtered_data = [card for card in response.data if card.get("review_status") != "deleted"]
    return filtered_data

@safe_db_operation("Mark cards as exported")
def mark_as_exported_db(supabase_client, document_ids: List[str]):
    """
    Mark cards as exported - simplified to only use existing columns.
    """
    timestamp = datetime.now(timezone.utc).isoformat()
    
    # Update reviewed_data status - only use columns that exist
    return supabase_client.table("reviewed_data").update({
        "exported_at": timestamp,
        "review_status": "exported",
        "updated_at": timestamp
    }).in_("document_id", document_ids).execute()

@safe_db_operation("Archive cards")
def archive_cards_db(supabase_client, document_ids: List[str]):
    """
    Archive cards - simplified to only use existing columns.
    """
    timestamp = datetime.now(timezone.utc).isoformat()
    
    # Update reviewed_data status - removed archived_at as it doesn't exist
    return supabase_client.table("reviewed_data").update({
        "review_status": "archived",
        "updated_at": timestamp
    }).in_("document_id", document_ids).execute()

@safe_db_operation("Delete cards")
def delete_cards_db(supabase_client, document_ids: List[str]):
    """
    Delete cards (mark as deleted) - simplified to only use existing columns.
    """
    timestamp = datetime.now(timezone.utc).isoformat()
    
    # Update reviewed_data status - removed deleted_at as it doesn't exist
    return supabase_client.table("reviewed_data").update({
        "review_status": "deleted",
        "updated_at": timestamp
    }).in_("document_id", document_ids).execute()

@safe_db_operation("Move cards")
def move_cards_db(supabase_client, document_ids: List[str], status: str):
    """
    Move cards to a different status - simplified to only use existing columns.
    """
    timestamp = datetime.now(timezone.utc).isoformat()
    
    # Update reviewed_data status
    return supabase_client.table("reviewed_data").update({
        "review_status": status,
        "updated_at": timestamp
    }).in_("document_id", document_ids).execute()

@safe_db_operation("Save manual review")
def save_manual_review_db(supabase_client, document_id: str, review_data: Dict[str, Any]):
    """
    Save manual review changes - simplified to only use existing columns.
    """
    timestamp = datetime.now(timezone.utc).isoformat()
    
    # Update reviewed_data - removed last_reviewed_by as it doesn't exist
    return supabase_client.table("reviewed_data").update({
        **review_data,
        "updated_at": timestamp
    }).eq("document_id", document_id).execute() 