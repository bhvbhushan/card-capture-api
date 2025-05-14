import os
import time
import tempfile
import traceback
import json
from datetime import datetime, timezone
# from app.services.document_service import process_image
from app.services.document_service import parse_card_with_gemini
# from app.services.gemini_service import run_gemini_review
from app.repositories.processing_jobs_repository import update_processing_job
from app.core.clients import supabase_client
from app.repositories.uploads_repository import insert_extracted_data_db
from app.repositories.reviewed_data_repository import upsert_reviewed_data
from app.repositories.upload_notifications_repository import insert_upload_notification

BUCKET = "cards-uploads"
MAX_RETRIES = 3
SLEEP_SECONDS = 1

def download_from_supabase(storage_path, local_path):
    res = supabase_client.storage.from_(BUCKET).download(storage_path.replace(f"{BUCKET}/", ""))
    if hasattr(res, 'error') and res.error:
        raise Exception(f"Supabase Storage download error: {res.error}")
    with open(local_path, "wb") as f:
        f.write(res)
    return local_path

def sync_card_fields_preferences(supabase_client, user_id, school_id, extracted_fields):
    """
    Ensure the settings table for the given user_id and school_id has all actual_field_name values from extracted_fields in preferences.card_fields.
    Adds missing fields with value True. Inserts row if not present.
    The card_fields keys are the actual_field_name values from Gemini output.
    """
    # Collect all unique actual_field_name values from extracted_fields
    actual_labels = set()
    for field_data in extracted_fields.values():
        if isinstance(field_data, dict):
            label = field_data.get("actual_field_name")
            if label:
                actual_labels.add(label)
    print(f"[Preferences Sync] Using actual_field_name labels from Gemini: {list(actual_labels)}")

    settings_query = supabase_client.table("settings").select("id, preferences").eq("user_id", user_id).eq("school_id", school_id).maybe_single().execute()
    settings_row = settings_query.data if settings_query and settings_query.data else None
    preferences = {}
    if settings_row:
        print(f"[Preferences Sync] Found existing settings row: id={settings_row.get('id')}")
        preferences = settings_row.get("preferences") or {}
        print(f"[Preferences Sync] DB card_fields: {settings_row.get('preferences', {}).get('card_fields')}")
        print(f"[Preferences Sync] New card_fields: {preferences.get('card_fields')}")
    else:
        print(f"[Preferences Sync] No settings row found. Will insert new row if needed.")
    card_fields = preferences.get("card_fields") if preferences else None
    new_labels = {label: True for label in actual_labels}
    if not card_fields or not isinstance(card_fields, dict) or not card_fields:
        print(f"[Preferences Sync] card_fields missing or invalid. Initializing with parsed labels: {list(new_labels.keys())}")
        card_fields = dict(new_labels)  # ensure new object
        preferences["card_fields"] = card_fields
        print(f"[Preferences Sync] Forcing upsert of card_fields in DB.")
        supabase_client.table("settings").upsert({
            "id": settings_row["id"],
            "user_id": user_id,
            "school_id": school_id,
            "preferences": preferences
        }).execute()
        # Fetch again to confirm
        updated_row = supabase_client.table("settings").select("id, preferences").eq("id", settings_row["id"]).maybe_single().execute()
        print(f"[Preferences Sync] After upsert, card_fields in DB: {updated_row.data.get('preferences', {}).get('card_fields') if updated_row and updated_row.data else None}")
        return
    updated = False
    for label in new_labels:
        if label not in card_fields:
            print(f"[Preferences Sync] Adding missing field to card_fields: {label}")
            card_fields[label] = True
            updated = True
    if not updated:
        print(f"[Preferences Sync] No new fields to add to card_fields.")
        card_fields = card_fields  # No change
    preferences["card_fields"] = card_fields
    if not settings_row:
        print(f"[Preferences Sync] Inserting new settings row for user_id={user_id}, school_id={school_id}")
        supabase_client.table("settings").insert({
            "user_id": user_id,
            "school_id": school_id,
            "preferences": preferences
        }).execute()
        print(f"[Preferences Sync] Inserted new settings row for user_id={user_id}, school_id={school_id}")
    else:
        if settings_row.get("preferences", {}).get("card_fields") != card_fields:
            print(f"[Preferences Sync] Updating settings preferences.card_fields for user_id={user_id}, school_id={school_id}")
            supabase_client.table("settings").update({"preferences": preferences}).eq("id", settings_row["id"]).execute()
            print(f"[Preferences Sync] Updated settings preferences.card_fields for user_id={user_id}, school_id={school_id}")
        else:
            print(f"[Preferences Sync] card_fields already up to date. No update needed.")

def process_job(job):
    job_id = job["id"]
    file_url = job["file_url"]
    user_id = job["user_id"]
    school_id = job["school_id"]
    event_id = job.get("event_id")
    print(f"Processing job {job_id} for user {user_id}, file {file_url}")
    tmp_file = None
    try:
        with tempfile.NamedTemporaryFile(delete=False, suffix=os.path.splitext(file_url)[1] or '.png') as tmp:
            tmp_file = tmp.name
        download_from_supabase(file_url, tmp_file)
        print(f"Downloaded to {tmp_file}")
        # extracted_fields = process_image(tmp_file)
        extracted_fields = parse_card_with_gemini(tmp_file)
        print(f"Extracted fields: {json.dumps(extracted_fields)[:200]}...")
        # Update extracted fields in extracted_data table before Gemini review
        supabase_client.table("extracted_data").update({"fields": extracted_fields}).eq("document_id", job_id).execute()
        print(f"Updated extracted data for document_id: {job_id}")

        # --- Preferences sync logic ---
        sync_card_fields_preferences(supabase_client, user_id, school_id, extracted_fields)
        # --- End preferences sync logic ---
        # run_gemini_review(job_id, extracted_fields, tmp_file)
        # --- New: Upsert reviewed_data and send notification ---
        now = datetime.now(timezone.utc).isoformat()
        reviewed_data = {
            "document_id": job_id,
            "fields": extracted_fields,
            "school_id": school_id,
            "user_id": user_id,
            "event_id": event_id,
            "image_path": job.get("image_path"),
            "review_status": "reviewed",
            "created_at": now,
            "updated_at": now
        }
        upsert_reviewed_data(supabase_client, reviewed_data)
        print(f"✅ Upserted reviewed_data for job {job_id}")
        # notification_data = {
        #     "document_id": job_id,
        #     "event": "review_completed",
        #     "status": "reviewed",
        #     "timestamp": now
        # }
        # insert_upload_notification(supabase_client, notification_data)
        # print(f"✅ Notification sent for review completed: {job_id}")
        # --- End new ---
        update_processing_job(supabase_client, job_id, {
            "status": "complete",
            "updated_at": now,
            "error_message": None
        })
        print(f"Job {job_id} complete.")
    except Exception as e:
        print(f"Error processing job {job_id}: {e}")
        traceback.print_exc()
        retries = job.get("retries", 0) + 1
        now = datetime.now(timezone.utc).isoformat()
        if retries < MAX_RETRIES:
            update_processing_job(supabase_client, job_id, {
                "status": "queued",
                "error_message": str(e),
                "updated_at": now,
                "retries": retries
            })
            print(f"Job {job_id} re-queued (retry {retries}).")
        else:
            update_processing_job(supabase_client, job_id, {
                "status": "failed",
                "error_message": str(e),
                "updated_at": now
            })
            print(f"Job {job_id} failed after {MAX_RETRIES} retries.")
    finally:
        if tmp_file and os.path.exists(tmp_file):
            os.remove(tmp_file)

def main():
    print("Starting CardCapture processing worker...")
    while True:
        try:
            jobs = supabase_client.table("processing_jobs").select("*").eq("status", "queued").order("created_at").limit(1).execute()
            if jobs.data and len(jobs.data) > 0:
                job = jobs.data[0]
                now = datetime.now(timezone.utc).isoformat()
                update_processing_job(supabase_client, job["id"], {
                    "status": "processing",
                    "updated_at": now
                })
                process_job(job)
            else:
                time.sleep(SLEEP_SECONDS)
        except Exception as e:
            print(f"Worker error: {e}")
            traceback.print_exc()
            time.sleep(SLEEP_SECONDS)

if __name__ == "__main__":
    main() 