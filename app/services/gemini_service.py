from datetime import datetime, timezone
import os
from app.core.clients import supabase_client
from app.services.document_service import get_gemini_review
from app.repositories.reviewed_data_repository import upsert_reviewed_data
from app.repositories.extracted_data_repository import get_extracted_data_by_document_id
from app.repositories.upload_notifications_repository import insert_upload_notification
import traceback

def run_gemini_review(document_id: str, extracted_fields_dict: dict, image_path: str):
    if not supabase_client:
        print("❌ Supabase client not available")
        return
    print(f"⏳ Background Task: Starting Gemini review for document_id: {document_id}")
    try:
        try:
            extracted_response = get_extracted_data_by_document_id(supabase_client, document_id)
            if not extracted_response:
                print(f"❌ No extracted data found for document_id: {document_id}")
                return
            event_id = extracted_response.get("event_id")
            school_id = extracted_response.get("school_id")
            print(f"📝 Found event_id: {event_id}, school_id: {school_id} for document: {document_id}")
        except Exception as db_e:
            print(f"❌ Error fetching extracted data: {db_e}")
            return
        gemini_reviewed_data = get_gemini_review(extracted_fields_dict, image_path)
        if not gemini_reviewed_data:
            print(f"⚠️ Gemini review failed or returned empty for {document_id}. Raising exception to trigger worker retry.")
            raise Exception("Gemini review failed or returned empty.")
        print(f"✅ Background Task: Gemini review completed for {document_id}")
        final_reviewed_fields = {}
        any_field_needs_review = False
        for field_name, review_data in gemini_reviewed_data.items():
            if isinstance(review_data, dict):
                final_reviewed_fields[field_name] = {
                    "value": review_data.get("value"),
                    "confidence": review_data.get("review_confidence", 0.0),
                    "requires_human_review": review_data.get("requires_human_review", False),
                    "review_notes": review_data.get("review_notes", ""),
                    "source": "gemini"
                }
                if review_data.get("requires_human_review"):
                    any_field_needs_review = True
            else:
                print(f"⚠️ Unexpected format for field '{field_name}': {review_data}")
                original_data = extracted_fields_dict.get(field_name, {})
                final_reviewed_fields[field_name] = {
                    "value": review_data if isinstance(review_data, str) else None,
                    "confidence": 0.0,
                    "requires_human_review": True,
                    "review_notes": "Unexpected data format from Gemini review",
                    "source": "gemini_error"
                }
                any_field_needs_review = True
        try:
            update_data = {
                "document_id": document_id,
                "fields": final_reviewed_fields,
                "review_status": "needs_human_review" if any_field_needs_review else "reviewed",
                "reviewed_at": datetime.now(timezone.utc).isoformat(),
                "event_id": event_id,
                "school_id": school_id
            }
            upsert_reviewed_data(supabase_client, update_data)
            print(f"✅ Background Task: Saved reviewed data for {document_id}")
            try:
                notification_data = {
                    "document_id": document_id,
                    "event": "review_completed",
                    "status": "needs_human_review" if any_field_needs_review else "reviewed",
                    "timestamp": datetime.now(timezone.utc).isoformat()
                }
                insert_upload_notification(supabase_client, notification_data)
                print(f"✅ Notification sent for review completed: {document_id}")
            except Exception as notif_error:
                print(f"⚠️ Failed to send notification: {notif_error}")
        except Exception as db_e:
            print(f"❌ Background Task: Supabase error saving reviewed data for {document_id}: {db_e}")
            raise db_e
    except Exception as e:
        print(f"❌ Background Task: Error during run_gemini_review for {document_id}: {e}")
        traceback.print_exc()
        raise 