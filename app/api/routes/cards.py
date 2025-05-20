from fastapi import APIRouter, Body
from typing import Union, List, Dict, Any
from app.controllers.cards_controller import (
    get_cards_controller,
    archive_cards_controller,
    mark_as_exported_controller,
    delete_cards_controller,
    move_cards_controller
)
from app.models.card import ArchiveCardsPayload, MarkExportedPayload, DeleteCardsPayload, MoveCardsPayload
from fastapi.responses import JSONResponse
from app.core.clients import supabase_client
from datetime import datetime, timezone
import traceback
import uuid

router = APIRouter(tags=["Cards"])

@router.get("/cards", response_model=List[Dict[str, Any]])
async def get_cards(event_id: Union[str, None] = None):
    return await get_cards_controller(event_id)

@router.post("/archive-cards")
async def archive_cards(payload: ArchiveCardsPayload):
    return await archive_cards_controller(payload)

@router.post("/mark-exported")
async def mark_as_exported(payload: MarkExportedPayload):
    return await mark_as_exported_controller(payload)

@router.post("/delete-cards")
async def delete_cards(payload: DeleteCardsPayload):
    return await delete_cards_controller(payload)

@router.post("/move-cards")
async def move_cards(payload: MoveCardsPayload):
    return await move_cards_controller(payload)

@router.post("/save-review/{document_id}")
async def save_manual_review(document_id: str, payload: Dict[str, Any] = Body(...)):
    """
    Updates a record in reviewed_data based on manual user edits.
    Only required fields determine if a card needs review.
    """
    if not supabase_client:
        return JSONResponse(status_code=503, content={"error": "Database client not available."})

    print(f"💾 Saving manual review for document_id: {document_id}")
    print(f"   Payload received: {payload}")
    
    updated_fields = payload.get("fields", {})
    frontend_status = payload.get("status")

    try:
        # 1. Fetch the current record from reviewed_data
        fetch_response = supabase_client.table("reviewed_data") \
                                        .select("fields, event_id, school_id") \
                                        .eq("document_id", document_id) \
                                        .maybe_single() \
                                        .execute()

        # Defensive: handle if fetch_response is None (e.g., 406 error from Supabase)
        if not fetch_response or not hasattr(fetch_response, "data"):
            print(f"  -> Error: Supabase query failed or returned no response for reviewed_data (document_id={document_id})")
            return JSONResponse(status_code=500, content={"error": "Supabase query failed for reviewed_data. Check Accept headers and Supabase client configuration."})

        if not fetch_response.data:
            # If no reviewed data exists yet, get event_id and school_id from extracted_data
            extracted_response = supabase_client.table("extracted_data") \
                .select("event_id, school_id, fields") \
                .eq("document_id", document_id) \
                .maybe_single() \
                .execute()
            # Defensive: handle if extracted_response is None
            if not extracted_response or not hasattr(extracted_response, "data"):
                print(f"  -> Error: Supabase query failed or returned no response for extracted_data (document_id={document_id})")
                return JSONResponse(status_code=500, content={"error": "Supabase query failed for extracted_data. Check Accept headers and Supabase client configuration."})
            if not extracted_response.data:
                print(f"  -> Error: No existing data found for {document_id}")
                return JSONResponse(status_code=404, content={"error": "Record not found."})
            event_id = extracted_response.data.get("event_id")
            school_id = extracted_response.data.get("school_id")
            current_fields_data = extracted_response.data.get("fields", {})
        else:
            event_id = fetch_response.data.get("event_id")
            school_id = fetch_response.data.get("school_id")
            current_fields_data = fetch_response.data.get("fields", {})

        # Define required fields that determine review status
        REQUIRED_FIELDS = ["address", "cell", "city", "state", "zip_code", "name", "email"]

        # 2. Update fields based on user input
        for key, field_data in updated_fields.items():
            if key in current_fields_data:
                # Update value and metadata for the edited field
                current_fields_data[key].update({
                    **field_data,
                    "reviewed": True,  # Mark as reviewed since it's a manual edit
                    "requires_human_review": False,  # No longer needs review
                    "confidence": 1.0,  # High confidence for manual edits
                    "source": "human_review",
                    "review_notes": "Manually reviewed"
                })
            else:
                # If the field doesn't exist, add it with full metadata
                current_fields_data[key] = {
                    **field_data,
                    "reviewed": True,
                    "requires_human_review": False,
                    "confidence": 1.0,
                    "source": "human_review",
                    "review_notes": "Manually reviewed"
                }

        # 3. Check if any required fields still need review
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

        # 4. Prepare data for update
        # Use the frontend status if provided, otherwise determine based on fields
        review_status = frontend_status if frontend_status else ("needs_human_review" if any_required_field_needs_review else "reviewed")
        
        update_payload = {
            "document_id": document_id,
            "fields": current_fields_data,
            "review_status": review_status,
            "reviewed_at": datetime.now(timezone.utc).isoformat(),
            "event_id": event_id,
            "school_id": school_id
        }

        # 5. Update the record in Supabase
        update_response = supabase_client.table("reviewed_data") \
                                         .upsert(update_payload, on_conflict="document_id") \
                                         .execute()

        print(f"✅ Successfully saved manual review for {document_id}")
        return JSONResponse(status_code=200, content={
            "message": "Review saved successfully",
            "status": update_payload["review_status"],
            "any_field_needs_review": any_required_field_needs_review
        })

    except Exception as e:
        print(f"❌ Error saving manual review for {document_id}: {e}")
        traceback.print_exc()
        return JSONResponse(status_code=500, content={"error": "Failed to save review."})

@router.post("/manual-entry")
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
        if not event_id or not fields:
            return JSONResponse(status_code=400, content={"error": "event_id and fields are required."})

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

        record = {
            "document_id": document_id,
            "fields": reviewed_fields,
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