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

@ensure_atomic_updates(["reviewed_data", "export_history"])
def mark_as_exported_db(supabase_client, document_ids: List[str]):
    """
    Mark cards as exported and create export history atomically.
    If either operation fails, both are rolled back.
    """
    try:
        timestamp = datetime.now(timezone.utc).isoformat()
        
        # Update reviewed_data status
        cards_response = supabase_client.table("reviewed_data").update({
            "exported_at": timestamp,
            "review_status": "exported"
        }).in_("document_id", document_ids).execute()
        
        if not validate_db_response(cards_response, "Update cards export status"):
            raise HTTPException(status_code=500, detail="Failed to update cards export status")
            
        # Create export history records
        export_records = [{
            "document_id": doc_id,
            "exported_at": timestamp,
            "export_type": "slate",  # or other export types
            "status": "success"
        } for doc_id in document_ids]
        
        history_response = supabase_client.table("export_history").insert(export_records).execute()
        if not validate_db_response(history_response, "Create export history"):
            raise HTTPException(status_code=500, detail="Failed to create export history")
            
        return {
            "cards": cards_response.data,
            "history": history_response.data
        }
        
    except Exception as e:
        error_details = handle_db_error(e, "Mark cards as exported")
        raise HTTPException(status_code=500, detail=error_details)

@ensure_atomic_updates(["reviewed_data", "archive_history"])
def archive_cards_db(supabase_client, document_ids: List[str]):
    """
    Archive cards and create archive history atomically.
    If either operation fails, both are rolled back.
    """
    try:
        timestamp = datetime.now(timezone.utc).isoformat()
        
        # Update reviewed_data status
        cards_response = supabase_client.table("reviewed_data").update({
            "review_status": "archived",
            "archived_at": timestamp
        }).in_("document_id", document_ids).execute()
        
        if not validate_db_response(cards_response, "Archive cards"):
            raise HTTPException(status_code=500, detail="Failed to archive cards")
            
        # Create archive history records
        archive_records = [{
            "document_id": doc_id,
            "archived_at": timestamp,
            "archive_reason": "user_initiated",
            "status": "success"
        } for doc_id in document_ids]
        
        history_response = supabase_client.table("archive_history").insert(archive_records).execute()
        if not validate_db_response(history_response, "Create archive history"):
            raise HTTPException(status_code=500, detail="Failed to create archive history")
            
        return {
            "cards": cards_response.data,
            "history": history_response.data
        }
        
    except Exception as e:
        error_details = handle_db_error(e, "Archive cards")
        raise HTTPException(status_code=500, detail=error_details)

@ensure_atomic_updates(["reviewed_data", "delete_history"])
def delete_cards_db(supabase_client, document_ids: List[str]):
    """
    Delete cards (mark as deleted) and create deletion history atomically.
    If either operation fails, both are rolled back.
    """
    try:
        timestamp = datetime.now(timezone.utc).isoformat()
        
        # Update reviewed_data status
        cards_response = supabase_client.table("reviewed_data").update({
            "review_status": "deleted",
            "deleted_at": timestamp
        }).in_("document_id", document_ids).execute()
        
        if not validate_db_response(cards_response, "Delete cards"):
            raise HTTPException(status_code=500, detail="Failed to delete cards")
            
        # Create deletion history records
        delete_records = [{
            "document_id": doc_id,
            "deleted_at": timestamp,
            "delete_reason": "user_initiated",
            "status": "success"
        } for doc_id in document_ids]
        
        history_response = supabase_client.table("delete_history").insert(delete_records).execute()
        if not validate_db_response(history_response, "Create delete history"):
            raise HTTPException(status_code=500, detail="Failed to create delete history")
            
        return {
            "cards": cards_response.data,
            "history": history_response.data
        }
        
    except Exception as e:
        error_details = handle_db_error(e, "Delete cards")
        raise HTTPException(status_code=500, detail=error_details)

@ensure_atomic_updates(["reviewed_data", "status_history"])
def move_cards_db(supabase_client, document_ids: List[str], status: str):
    """
    Move cards to a different status and create status change history atomically.
    If either operation fails, both are rolled back.
    """
    try:
        timestamp = datetime.now(timezone.utc).isoformat()
        
        # Update reviewed_data status
        cards_response = supabase_client.table("reviewed_data").update({
            "review_status": status,
            "updated_at": timestamp
        }).in_("document_id", document_ids).execute()
        
        if not validate_db_response(cards_response, "Move cards"):
            raise HTTPException(status_code=500, detail=f"Failed to move cards to status: {status}")
            
        # Create status change history records
        status_records = [{
            "document_id": doc_id,
            "old_status": None,  # Would need to fetch previous status if needed
            "new_status": status,
            "changed_at": timestamp,
            "change_reason": "user_initiated"
        } for doc_id in document_ids]
        
        history_response = supabase_client.table("status_history").insert(status_records).execute()
        if not validate_db_response(history_response, "Create status history"):
            raise HTTPException(status_code=500, detail="Failed to create status change history")
            
        return {
            "cards": cards_response.data,
            "history": history_response.data
        }
        
    except Exception as e:
        error_details = handle_db_error(e, "Move cards")
        raise HTTPException(status_code=500, detail=error_details)

@ensure_atomic_updates(["reviewed_data", "review_history"])
def save_manual_review_db(supabase_client, document_id: str, review_data: Dict[str, Any], reviewer_id: str):
    """
    Save manual review changes and create review history atomically.
    If either operation fails, both are rolled back.
    """
    try:
        timestamp = datetime.now(timezone.utc).isoformat()
        
        # Update reviewed_data
        review_response = supabase_client.table("reviewed_data").update({
            **review_data,
            "updated_at": timestamp,
            "last_reviewed_by": reviewer_id
        }).eq("document_id", document_id).execute()
        
        if not validate_db_response(review_response, "Save manual review"):
            raise HTTPException(status_code=500, detail="Failed to save review changes")
            
        # Create review history record
        history_record = {
            "document_id": document_id,
            "reviewer_id": reviewer_id,
            "reviewed_at": timestamp,
            "changes_made": review_data.get("changes", []),
            "review_type": "manual"
        }
        
        history_response = supabase_client.table("review_history").insert(history_record).execute()
        if not validate_db_response(history_response, "Create review history"):
            raise HTTPException(status_code=500, detail="Failed to create review history")
            
        return {
            "review": review_response.data[0] if review_response.data else None,
            "history": history_response.data[0] if history_response.data else None
        }
        
    except Exception as e:
        error_details = handle_db_error(e, "Save manual review")
        raise HTTPException(status_code=500, detail=error_details) 