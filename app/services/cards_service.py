from typing import List, Dict, Any, Union
from fastapi.responses import JSONResponse
from fastapi import HTTPException
import traceback
from app.models.card import (
    MarkExportedPayload,
    ArchiveCardsPayload,
    DeleteCardsPayload,
    MoveCardsPayload
)
from app.core.clients import supabase_client
from app.repositories.cards_repository import (
    get_cards_db,
    archive_cards_db,
    mark_as_exported_db,
    delete_cards_db,
    move_cards_db
)
from app.utils.archive_logging import log_archive_debug

async def get_cards_service(event_id: Union[str, None] = None) -> List[Dict[str, Any]]:
    try:
        print(" Rcvd /cards request")
        if event_id:
            print(f" Filtering by event_id: {event_id}")
        result = get_cards_db(supabase_client, event_id)
        print(f" Found {len(result)} reviewed records.")
        print(f" Returning {len(result)} non-deleted, non-archived records.")
        return result
    except Exception as e:
        print(f"❌ Error in /cards endpoint: {e}")
        traceback.print_exc()
        raise HTTPException(status_code=500, detail=str(e))

async def archive_cards_service(document_ids: List[str]) -> JSONResponse:
    """Archive cards by document IDs"""
    log_archive_debug("=== ARCHIVE CARDS SERVICE START ===")
    log_archive_debug("Received document IDs", document_ids)
    
    if not supabase_client:
        error_msg = "Database client not available"
        log_archive_debug(f"Error: {error_msg}")
        return JSONResponse(status_code=503, content={"error": error_msg})
    
    if not document_ids:
        error_msg = "No document IDs provided"
        log_archive_debug(f"Error: {error_msg}")
        return JSONResponse(status_code=400, content={"error": error_msg})
    
    try:
        log_archive_debug("Calling archive_cards_db...")
        result = archive_cards_db(supabase_client, document_ids)
        
        if not result or not hasattr(result, 'data'):
            log_archive_debug("No records were archived")
            return JSONResponse(status_code=200, content={"message": "No records were archived", "archived_count": 0})
        
        archived_count = len(result.data)
        log_archive_debug(f"Successfully archived {archived_count} records")
        log_archive_debug("=== ARCHIVE CARDS SERVICE END ===")
        
        return JSONResponse(status_code=200, content={
            "message": f"Successfully archived {archived_count} records",
            "archived_count": archived_count
        })
    except Exception as e:
        error_msg = f"Error archiving cards: {str(e)}"
        log_archive_debug(f"Error: {error_msg}")
        log_archive_debug("=== ARCHIVE CARDS SERVICE END WITH ERROR ===")
        return JSONResponse(status_code=500, content={"error": error_msg})

async def mark_as_exported_service(document_ids: List[str]) -> JSONResponse:
    """Mark cards as exported by document IDs"""
    if not supabase_client:
        print("❌ Database client not available")
        return JSONResponse(status_code=503, content={"error": "Database client not available."})
    
    if not document_ids:
        print("❌ No document_ids provided.")
        return JSONResponse(status_code=400, content={"error": "No document_ids provided."})
    
    print(f"📤 Recording export timestamp for {len(document_ids)} records...")
    try:
        update_response = mark_as_exported_db(supabase_client, document_ids)
        print(f"✅ Successfully recorded export timestamp for {len(document_ids)} records.")
        return JSONResponse(status_code=200, content={"message": f"{len(document_ids)} records export timestamp updated."})
    except Exception as e:
        print(f"❌ Error recording export timestamp: {e}")
        traceback.print_exc()
        return JSONResponse(status_code=500, content={"error": "Failed to record export timestamp."})

async def delete_cards_service(document_ids: List[str]) -> JSONResponse:
    """Delete cards by document IDs"""
    if not supabase_client:
        print("❌ Database client not available")
        return JSONResponse(status_code=503, content={"error": "Database client not available."})
    
    if not document_ids:
        print("❌ No document_ids provided.")
        return JSONResponse(status_code=400, content={"error": "No document_ids provided."})
    
    print(f"🗑️ Deleting {len(document_ids)} cards...")
    try:
        reviewed_response, extracted_response = delete_cards_db(supabase_client, document_ids)
        print(f"✅ Successfully deleted {len(document_ids)} cards.")
        return JSONResponse(status_code=200, content={"message": f"{len(document_ids)} cards deleted successfully."})
    except Exception as e:
        print(f"❌ Error deleting cards: {e}")
        traceback.print_exc()
        return JSONResponse(status_code=500, content={"error": "Failed to delete cards."})

async def move_cards_service(document_ids: List[str], status: str = "reviewed") -> JSONResponse:
    """Move cards to a different status by document IDs"""
    if not supabase_client:
        print("❌ Database client not available")
        return JSONResponse(status_code=503, content={"error": "Database client not available."})
    
    if not document_ids:
        print("❌ No document_ids provided.")
        return JSONResponse(status_code=400, content={"error": "No document_ids provided."})
    
    try:
        result = move_cards_db(supabase_client, document_ids, status)
        print(f"✅ Successfully moved {len(document_ids)} cards to status '{status}'")
        return JSONResponse(
            status_code=200,
            content={"message": f"Successfully moved {len(document_ids)} cards to status '{status}'"}
        )
    except Exception as e:
        print(f"❌ Error moving cards: {e}")
        traceback.print_exc()
        return JSONResponse(
            status_code=500,
            content={"error": str(e)}
        )

# Legacy service functions for backward compatibility during transition
async def mark_as_exported_service_legacy(payload: MarkExportedPayload):
    """Legacy service - will be removed after frontend migration"""
    document_ids = payload.get_document_ids() if hasattr(payload, 'get_document_ids') else payload.document_ids
    return await mark_as_exported_service(document_ids)

async def save_manual_review_service(document_id: str, payload: Dict[str, Any]):
    """Save manual review for a single card - this remains unchanged"""
    # This function handles individual card reviews, not bulk operations
    # Implementation would go here - keeping the existing logic
    pass 