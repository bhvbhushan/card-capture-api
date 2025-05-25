from typing import List, Dict, Any, Union
from datetime import datetime, timezone
from app.utils.archive_logging import log_archive_debug

def get_cards_db(supabase_client, event_id: Union[str, None] = None) -> List[Dict[str, Any]]:
    print(" Rcvd /cards request")
    if event_id:
        print(f" Filtering by event_id: {event_id}")
    reviewed_query = supabase_client.table("reviewed_data").select("*")
    if event_id:
        reviewed_query = reviewed_query.eq("event_id", event_id)
    reviewed_response = reviewed_query.execute()
    reviewed_data = reviewed_response.data
    print(f" Found {len(reviewed_data)} reviewed records.")
    filtered_data = [card for card in reviewed_data if card.get("review_status") != "deleted"]
    print(f" Returning {len(filtered_data)} non-deleted records.")
    return filtered_data

def archive_cards_db(supabase_client, document_ids: List[str]):
    log_archive_debug("=== ARCHIVE CARDS DB START ===")
    log_archive_debug("Document IDs to archive", document_ids)
    
    # First check if records exist and their current status
    log_archive_debug("Checking existing records...")
    existing_query = supabase_client.table("reviewed_data").select("*").in_("document_id", document_ids).execute()
    existing_records = existing_query.data
    
    # Log if no records were found
    if not existing_records:
        log_archive_debug("No records found with the provided document IDs")
        return {"data": [], "count": 0}
    
    # Log the full state of each record
    for record in existing_records:
        log_archive_debug(f"Record {record['document_id']} full state:", {
            "document_id": record.get("document_id"),
            "review_status": record.get("review_status"),
            "status": record.get("status"),
            "deleted": record.get("deleted"),
            "reviewed_at": record.get("reviewed_at")
        })
    
    # Filter out records that are already archived
    records_to_archive = [r for r in existing_records if r.get("review_status") != "archived"]
    log_archive_debug("Records to archive (excluding already archived)", [
        {
            "document_id": r.get("document_id"),
            "current_status": r.get("review_status")
        } for r in records_to_archive
    ])
    
    if not records_to_archive:
        log_archive_debug("No records need archiving - all are already archived")
        return {"data": [], "count": 0}
    
    timestamp = datetime.now(timezone.utc).isoformat()
    update_payload = {
        "review_status": "archived",
        "reviewed_at": timestamp
    }
    log_archive_debug("Update payload", update_payload)
    
    try:
        result = supabase_client.table('reviewed_data') \
            .update(update_payload) \
            .in_("document_id", [r["document_id"] for r in records_to_archive]) \
            .execute()
        
        # Log the updated records
        updated_query = supabase_client.table("reviewed_data").select("*").in_("document_id", [r["document_id"] for r in records_to_archive]).execute()
        for record in updated_query.data:
            log_archive_debug(f"Record {record['document_id']} after archive:", {
                "review_status": record.get("review_status"),
                "reviewed_at": record.get("reviewed_at")
            })
        
        log_archive_debug("Archive operation result", result)
        log_archive_debug("=== ARCHIVE CARDS DB END ===")
        return result
    except Exception as e:
        log_archive_debug(f"Error during archive operation: {str(e)}")
        log_archive_debug("=== ARCHIVE CARDS DB END WITH ERROR ===")
        raise e

def mark_as_exported_db(supabase_client, document_ids: List[str]):
    timestamp = datetime.now(timezone.utc).isoformat()
    return supabase_client.table('reviewed_data') \
        .update({"exported_at": timestamp, "review_status": "exported"}) \
        .in_("document_id", document_ids) \
        .execute()

def delete_cards_db(supabase_client, document_ids: List[str]):
    timestamp = datetime.now(timezone.utc).isoformat()
    # Use review_status to mark as deleted instead of a deleted column
    reviewed_response = supabase_client.table('reviewed_data') \
        .update({"review_status": "deleted", "reviewed_at": timestamp}) \
        .in_("document_id", document_ids) \
        .execute()
    
    # Try to update extracted_data if it exists, but don't fail if it doesn't
    try:
        extracted_response = supabase_client.table('extracted_data') \
            .update({"review_status": "deleted", "updated_at": timestamp}) \
            .in_("document_id", document_ids) \
            .execute()
    except Exception as e:
        print(f"Warning: Could not update extracted_data table: {e}")
        extracted_response = None
    
    return reviewed_response, extracted_response

def move_cards_db(supabase_client, document_ids: List[str], status: str):
    return supabase_client.table('reviewed_data') \
        .update({"status": status}) \
        .in_("document_id", document_ids) \
        .execute() 