import os
import time
import tempfile
import traceback
import json
from datetime import datetime, timezone
from app.services.document_service import parse_card_with_gemini, validate_address_with_google
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

def sync_card_fields_preferences(supabase_client, user_id, school_id, docai_fields):
    """
    Ensure the schools table for the given school_id has all fields from docai_fields in card_fields.
    Adds missing fields with enabled=True and required=False. Updates school record if not present.
    """
    # Collect all unique field names from docai_fields
    field_names = set(docai_fields.keys())
    print(f"[Preferences Sync] Using field names from DocAI: {list(field_names)}")

    # First, get the current school settings
    school_query = supabase_client.table("schools").select("id, card_fields").eq("id", school_id).maybe_single().execute()
    school_row = school_query.data if school_query and school_query.data else None
    
    if school_row:
        print(f"[Preferences Sync] Found existing school row: id={school_row.get('id')}")
        card_fields = school_row.get("card_fields", {})
        print(f"[Preferences Sync] Current card_fields: {json.dumps(card_fields, indent=2)}")
    else:
        print(f"[Preferences Sync] No school row found. Will insert new row.")
        card_fields = {}

    # Update existing fields with required flags from settings
    for field_name in field_names:
        if field_name in card_fields:
            # Preserve existing settings
            field_settings = card_fields[field_name]
            print(f"[Preferences Sync] Preserving settings for {field_name}: {json.dumps(field_settings)}")
        else:
            # Initialize new fields with required=False by default
            card_fields[field_name] = {
                "enabled": True,
                "required": False  # Default to False
            }
            print(f"[Preferences Sync] Initializing new field {field_name} with required=False")

    # Update school record with modified card_fields
    update_payload = {
        "id": school_id,
        "card_fields": card_fields
    }
    
    # Update the school record
    print(f"[Preferences Sync] Updating school with card_fields: {json.dumps(card_fields, indent=2)}")
    supabase_client.table("schools").update(update_payload).eq("id", school_id).execute()
    
    # Verify the update
    updated_query = supabase_client.table("schools").select("card_fields").eq("id", school_id).maybe_single().execute()
    if updated_query and updated_query.data:
        print(f"[Preferences Sync] Verified updated school settings: {json.dumps(updated_query.data.get('card_fields', {}), indent=2)}")
    else:
        print("[Preferences Sync] Failed to verify school settings update")

def process_job(job):
    job_id = job["id"]
    file_url = job["file_url"]
    user_id = job["user_id"]
    school_id = job["school_id"]
    event_id = job.get("event_id")
    print(f"Processing job {job_id} for user {user_id}, school {school_id}")
    tmp_file = None
    try:
        with tempfile.NamedTemporaryFile(delete=False, suffix=os.path.splitext(file_url)[1] or '.png') as tmp:
            tmp_file = tmp.name
        download_from_supabase(file_url, tmp_file)
        print(f"Downloaded to {tmp_file}")
        
        # Use DocAI fields from processing_jobs.result_json
        docai_fields = job.get("result_json")
        if not docai_fields:
            raise Exception("No DocAI fields found in processing_jobs.result_json")
            
        # Debug logging for raw DocAI response
        print("\n=== Document AI Raw Response ===")
        print(json.dumps(docai_fields, indent=2))
        print("=== End Document AI Response ===\n")

        # Write logs to file
        with open('worker_debug.log', 'w') as f:
            f.write("=== Document AI Raw Response ===\n")
            f.write(json.dumps(docai_fields, indent=2))
            f.write("\n=== End Document AI Response ===\n\n")
            
        # Sync preferences before processing
        sync_card_fields_preferences(supabase_client, user_id, school_id, docai_fields)
        
        # Get the latest school settings to ensure we have the correct required flags
        school_query = supabase_client.table("schools").select("card_fields").eq("id", school_id).maybe_single().execute()
        if school_query and school_query.data:
            card_fields = school_query.data.get("card_fields", {})
            print("[Worker DEBUG] Retrieved school settings:")
            print(json.dumps(card_fields, indent=2))
            
            # Update DocAI fields with required flags from school settings
            for field_name, field_data in docai_fields.items():
                if field_name in card_fields:
                    field_settings = card_fields[field_name]
                    field_data["required"] = field_settings.get("required", False)  # Default to False
                    field_data["enabled"] = field_settings.get("enabled", True)
                    print(f"[Worker DEBUG] Updated {field_name} with required={field_data['required']}")
                else:
                    print(f"[Worker DEBUG] No settings found for {field_name}, defaulting required=False")
                    field_data["required"] = False
                    field_data["enabled"] = True
        
        # Debug logging for DocAI fields
        print("[Worker DEBUG] DocAI fields with required flags:")
        print(json.dumps(docai_fields, indent=2))
        
        # Get city and state from zip code using Google Maps
        if 'zip_code' in docai_fields and docai_fields['zip_code'].get('value'):
            zip_code = docai_fields['zip_code']['value']
            address = docai_fields.get('address', {}).get('value', '')
            print(f"[Worker DEBUG] Validating address with zip code: {zip_code}")
            validation_result = validate_address_with_google(address, zip_code)
            if validation_result:
                print(f"[Worker DEBUG] Address validation result: {json.dumps(validation_result, indent=2)}")
                # Add city and state from validation
                docai_fields['city'] = {
                    "value": validation_result['city'],
                    "confidence": 0.95,
                    "source": "zip_validation"
                }
                docai_fields['state'] = {
                    "value": validation_result['state'],
                    "confidence": 0.95,
                    "source": "zip_validation"
                }
                print(f"[Worker DEBUG] Added city: {validation_result['city']} and state: {validation_result['state']} from zip validation")
        
        # Run Gemini enhancement with DocAI fields (now including required flags)
        gemini_fields = parse_card_with_gemini(tmp_file, docai_fields)
        
        # Ensure required flags are preserved in the final output
        for field_name, field_data in gemini_fields.items():
            if field_name in docai_fields:
                field_data["required"] = docai_fields[field_name].get("required", False)  # Default to False
                field_data["enabled"] = docai_fields[field_name].get("enabled", True)
                # If field is required and empty, mark for review
                if field_data.get("required", False) and not field_data.get("value"):
                    field_data["requires_human_review"] = True
                    field_data["review_notes"] = "Required field is empty"
                # If field is required and has low confidence, mark for review
                elif field_data.get("required", False) and field_data.get("confidence", 0.0) < 0.7:
                    field_data["requires_human_review"] = True
                    field_data["review_notes"] = "Required field has low confidence"
        
        # Debug logging for Gemini response
        print("[Worker DEBUG] Gemini response with required flags:")
        print(json.dumps(gemini_fields, indent=2))

        # Add Gemini fields to log file
        with open('worker_debug.log', 'a') as f:
            f.write("=== Gemini Processed Fields ===\n")
            f.write(json.dumps(gemini_fields, indent=2))
            f.write("\n=== End Gemini Fields ===\n\n")
        
        now = datetime.now(timezone.utc).isoformat()
        reviewed_data = {
            "document_id": job_id,
            "fields": gemini_fields,
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
        update_processing_job(supabase_client, job_id, {
            "status": "complete",
            "updated_at": now,
            "error_message": None
        })
        print(f"Job {job_id} complete.")
    except Exception as e:
        print(f"Error processing job {job_id}: {e}")
        traceback.print_exc()
        update_processing_job(supabase_client, job_id, {
            "status": "error",
            "updated_at": datetime.now(timezone.utc).isoformat(),
            "error_message": str(e)
        })
    finally:
        if tmp_file and os.path.exists(tmp_file):
            os.unlink(tmp_file)

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