from fastapi import APIRouter, Body, HTTPException
from fastapi.responses import JSONResponse
from typing import Dict, Any, List, Union
from datetime import datetime, timezone
import traceback
import uuid

from app.models.card import BulkActionPayload, MarkExportedPayload
from app.services.cards_service import (
    mark_as_exported_service,
    archive_cards_service,
    delete_cards_service,
    move_cards_service,
    save_manual_review_service,
    get_cards_service
)
from app.core.clients import supabase_client
from app.repositories.reviewed_data_repository import upsert_reviewed_data
# Removed import: canonicalize_fields - no longer using canonicalization
from app.utils.field_utils import filter_combined_fields

router = APIRouter()

# Define required fields that determine review status
REQUIRED_FIELDS = ["address", "cell", "city", "state", "zip_code", "name", "email"]

@router.get("/cards", response_model=List[Dict[str, Any]])
async def get_cards(event_id: Union[str, None] = None):
    return await get_cards_service(event_id)

@router.post("/archive-cards")
async def archive_cards(payload: BulkActionPayload):
    """
    Archive cards - standardized endpoint
    """
    print(f"📁 Archive cards - document_ids: {payload.document_ids}")
    
    if not payload.document_ids:
        return JSONResponse(status_code=400, content={"error": "No document_ids provided"})
    
    return await archive_cards_service(payload.document_ids)

@router.post("/mark-exported")
async def mark_as_exported(payload: BulkActionPayload):
    """
    Mark cards as exported - standardized endpoint
    """
    print(f"📤 Mark as exported - document_ids: {payload.document_ids}")
    
    if not payload.document_ids:
        return JSONResponse(status_code=400, content={"error": "No document_ids provided"})
    
    return await mark_as_exported_service(payload.document_ids)

@router.post("/debug-mark-exported")
async def debug_mark_exported(payload: Dict[str, Any] = Body(...)):
    """Debug endpoint to see what payload is being sent"""
    print(f"🐛 DEBUG: Raw payload received: {payload}")
    print(f"🐛 DEBUG: Payload type: {type(payload)}")
    print(f"🐛 DEBUG: Payload keys: {list(payload.keys()) if isinstance(payload, dict) else 'Not a dict'}")
    
    document_ids = None
    if isinstance(payload, dict):
        document_ids = payload.get('document_ids') or payload.get('documentIds') or payload.get('ids')
    
    print(f"🐛 DEBUG: Extracted document_ids: {document_ids}")
    
    return JSONResponse(status_code=200, content={
        "received_payload": payload,
        "extracted_document_ids": document_ids
    })

@router.post("/delete-cards")
async def delete_cards(payload: BulkActionPayload):
    """
    Delete cards - standardized endpoint
    """
    print(f"🗑️ Delete cards - document_ids: {payload.document_ids}")
    
    if not payload.document_ids:
        return JSONResponse(status_code=400, content={"error": "No document_ids provided"})
    
    return delete_cards_service(payload.document_ids)

@router.post("/move-cards")
async def move_cards(payload: BulkActionPayload):
    """
    Move cards - standardized endpoint
    """
    print(f"📦 Move cards - document_ids: {payload.document_ids}, status: {payload.status}")
    
    if not payload.document_ids:
        return JSONResponse(status_code=400, content={"error": "No document_ids provided"})
    
    status = payload.status or "reviewed"
    return move_cards_service(payload.document_ids, status)

@router.post("/save-review/{document_id}")
async def save_manual_review(document_id: str, payload: Dict[str, Any] = Body(...)):
    """
    Save manual review changes for a card
    """
    try:
        # Get current card data
        current_card = supabase_client.table("reviewed_data").select("*").eq("document_id", document_id).maybe_single().execute()
        if not current_card or not current_card.data:
            raise HTTPException(status_code=404, detail="Card not found")

        current_fields_data = current_card.data.get("fields", {})
        updated_fields = payload.get("fields", {})
        frontend_status = payload.get("status")

        # Note: Canonicalization removed - field names from frontend are used directly

        # Update fields based on user input
        for key, field_data in updated_fields.items():
            if key in current_fields_data:
                # Preserve the original review status
                current_fields_data[key].update({
                    **field_data,
                    "value": field_data.get("value", current_fields_data[key].get("value", "")),
                    "reviewed": field_data.get("reviewed", current_fields_data[key].get("reviewed", False)),
                    "requires_human_review": field_data.get("requires_human_review", current_fields_data[key].get("requires_human_review", False)),
                    "review_notes": field_data.get("review_notes", current_fields_data[key].get("review_notes", "")),
                    "source": "human_review"
                })
            else:
                # For new fields, set default values
                current_fields_data[key] = {
                    **field_data,
                    "reviewed": False,
                    "requires_human_review": False,
                    "review_notes": "",
                    "source": "human_review"
                }

        # Check if any required fields still need review
        any_required_field_needs_review = False
        for field_name in REQUIRED_FIELDS:
            field_data = current_fields_data.get(field_name, {})
            if isinstance(field_data, dict):
                # A field needs review if it's marked as requiring review
                requires_review = field_data.get("requires_human_review", True)
                if requires_review:
                    print(f"Field {field_name} needs review")
                    any_required_field_needs_review = True
                    break

        # Use the frontend status if provided, otherwise determine based on fields
        review_status = frontend_status if frontend_status else ("needs_human_review" if any_required_field_needs_review else "reviewed")

        # Filter out combined fields before saving
        filtered_fields = filter_combined_fields(current_fields_data)

        # Update the card
        update_data = {
            "document_id": document_id,
            "fields": filtered_fields,  # Use filtered fields without combined address fields
            "review_status": review_status,
            "updated_at": datetime.now(timezone.utc).isoformat(),
            "school_id": current_card.data.get("school_id"),  # Preserve school_id
            "event_id": current_card.data.get("event_id"),    # Preserve event_id
            "image_path": current_card.data.get("image_path") # Preserve image_path
        }

        response = upsert_reviewed_data(supabase_client, update_data)
        return response.data[0] if response.data else None

    except Exception as e:
        print(f"Error saving review: {str(e)}")
        raise HTTPException(status_code=500, detail=str(e))

@router.post("/cards/manual")
async def manual_entry(payload: Dict[str, Any] = Body(...)):
    """
    Create a new manual entry in reviewed_data with review_status='reviewed' and no image.
    Expects: { event_id, school_id, fields: { ... } }
    """
    if not supabase_client:
        return JSONResponse(status_code=503, content={"error": "Database client not available."})

    try:
        event_id = payload.get("event_id")
        school_id = payload.get("school_id")
        fields = payload.get("fields", {})
        if not event_id or not school_id or not fields:
            return JSONResponse(status_code=400, content={"error": "event_id, school_id, and fields are required."})

        # Generate a new document_id
        document_id = str(uuid.uuid4())
        now = datetime.now(timezone.utc).isoformat()

        # Mark all fields as reviewed, not requiring human review, confidence 1.0
        reviewed_fields = {}
        for key, field in fields.items():
            reviewed_fields[key] = {
                **field,
                "reviewed": True,
                "requires_human_review": False,
                "confidence": 1.0,
                "source": "manual_entry",
                "review_notes": "Manually entered"
            }

        # Filter out combined fields before saving
        filtered_fields = filter_combined_fields(reviewed_fields)

        record = {
            "document_id": document_id,
            "fields": filtered_fields,  # Use filtered fields without combined address fields
            "review_status": "reviewed",
            "reviewed_at": now,
            "event_id": event_id,
            "school_id": school_id,
            "image_path": None
        }
        response = supabase_client.table("reviewed_data").insert(record).execute()
        if response.data:
            return JSONResponse(status_code=200, content={"message": "Manual entry created", "document_id": document_id, "record": response.data[0]})
        else:
            return JSONResponse(status_code=500, content={"error": "Failed to insert manual entry."})
    except Exception as e:
        print(f"❌ Error creating manual entry: {e}")
        traceback.print_exc()
        return JSONResponse(status_code=500, content={"error": str(e)}) 