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

def log_debug(message, data=None):
    """Write debug message and optional data to worker_debug.log"""
    timestamp = datetime.now(timezone.utc).isoformat()
    with open('worker_debug.log', 'a') as f:
        f.write(f"\n[{timestamp}] {message}\n")
        if data:
            if isinstance(data, (dict, list)):
                f.write(json.dumps(data, indent=2))
            else:
                f.write(str(data))
            f.write("\n")

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
    log_debug("Using field names from DocAI", list(field_names))

    # First, get the current school settings
    school_query = supabase_client.table("schools").select("id, card_fields").eq("id", school_id).maybe_single().execute()
    school_row = school_query.data if school_query and school_query.data else None
    
    if school_row:
        log_debug(f"Found existing school row: id={school_row.get('id')}")
        card_fields = school_row.get("card_fields", {})
        log_debug("Current card_fields", card_fields)
    else:
        log_debug("No school row found. Will insert new row.")
        card_fields = {}

    # Update existing fields with required flags from settings
    for field_name in field_names:
        if field_name in card_fields:
            # Preserve existing settings
            field_settings = card_fields[field_name]
            log_debug(f"Preserving settings for {field_name}", field_settings)
        else:
            # Initialize new fields with required=False by default
            card_fields[field_name] = {
                "enabled": True,
                "required": False  # Default to False
            }
            log_debug(f"Initializing new field {field_name} with required=False")

    # Update school record with modified card_fields
    update_payload = {
        "id": school_id,
        "card_fields": card_fields
    }
    
    # Update the school record
    log_debug("Updating school with card_fields", card_fields)
    supabase_client.table("schools").update(update_payload).eq("id", school_id).execute()
    
    # Verify the update
    updated_query = supabase_client.table("schools").select("card_fields").eq("id", school_id).maybe_single().execute()
    if updated_query and updated_query.data:
        log_debug("Verified updated school settings", updated_query.data.get('card_fields', {}))
    else:
        log_debug("Failed to verify school settings update")

def process_job(job):
    job_id = job["id"]
    file_url = job["file_url"]
    user_id = job["user_id"]
    school_id = job["school_id"]
    event_id = job.get("event_id")
    log_debug("=== PROCESSING JOB START ===")
    log_debug("Job Details", {
        "Job ID": job_id,
        "User ID": user_id,
        "School ID": school_id,
        "Event ID": event_id,
        "File URL": file_url
    })
    
    tmp_file = None
    try:
        with tempfile.NamedTemporaryFile(delete=False, suffix=os.path.splitext(file_url)[1] or '.png') as tmp:
            tmp_file = tmp.name
        download_from_supabase(file_url, tmp_file)
        log_debug(f"Downloaded file to: {tmp_file}")
        
        # Use DocAI fields from processing_jobs.result_json
        docai_fields = job.get("result_json")
        if not docai_fields:
            raise Exception("No DocAI fields found in processing_jobs.result_json")
            
        log_debug("=== DOCAI FIELDS FROM JOB ===", docai_fields)
        
        # Sync preferences before processing
        log_debug("=== SYNCING CARD FIELD PREFERENCES ===")
        sync_card_fields_preferences(supabase_client, user_id, school_id, docai_fields)
        
        # Get the latest school settings
        log_debug("=== RETRIEVING SCHOOL SETTINGS ===")
        school_query = supabase_client.table("schools").select("card_fields").eq("id", school_id).maybe_single().execute()
        if school_query and school_query.data:
            card_fields = school_query.data.get("card_fields", {})
            log_debug("School settings", card_fields)
            
            # Update DocAI fields with required flags
            log_debug("=== UPDATING FIELDS WITH REQUIRED FLAGS ===")
            for field_name, field_data in docai_fields.items():
                if field_name in card_fields:
                    field_settings = card_fields[field_name]
                    field_data["required"] = field_settings.get("required", False)
                    field_data["enabled"] = field_settings.get("enabled", True)
                    log_debug(f"Field: {field_name}", {
                        "Required": field_data['required'],
                        "Enabled": field_data['enabled']
                    })
                else:
                    log_debug(f"Field: {field_name} (no settings found, using defaults)")
                    field_data["required"] = False
                    field_data["enabled"] = True
        
        # Debug logging for DocAI fields after updates
        log_debug("=== UPDATED DOCAI FIELDS ===", docai_fields)
        
        # Get city and state from zip code using Google Maps
        if 'zip_code' in docai_fields and docai_fields['zip_code'].get('value'):
            zip_code = docai_fields['zip_code']['value']
            address = docai_fields.get('address', {}).get('value', '')
            log_debug("=== VALIDATING ADDRESS ===", {
                "Zip Code": zip_code,
                "Address": address
            })
            validation_result = validate_address_with_google(address, zip_code)
            if validation_result:
                log_debug("Address validation result", validation_result)
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
                log_debug(f"Added city: {validation_result['city']} and state: {validation_result['state']} from zip validation")
        
        # Run Gemini enhancement
        log_debug("=== RUNNING GEMINI ENHANCEMENT ===")
        gemini_fields = parse_card_with_gemini(tmp_file, docai_fields)
        
        # Ensure required flags are preserved
        log_debug("=== FINALIZING FIELD DATA ===")
        for field_name, field_data in gemini_fields.items():
            if field_name in docai_fields:
                field_data["required"] = docai_fields[field_name].get("required", False)
                field_data["enabled"] = docai_fields[field_name].get("enabled", True)
                # If field is required and empty, mark for review
                if field_data.get("required", False) and not field_data.get("value"):
                    field_data["requires_human_review"] = True
                    field_data["review_notes"] = "Required field is empty"
                    log_debug(f"Field {field_name} marked for review: Required field is empty")
                # If field is required and has low confidence, mark for review
                elif field_data.get("required", False) and field_data.get("confidence", 0.0) < 0.7:
                    field_data["requires_human_review"] = True
                    field_data["review_notes"] = "Required field has low confidence"
                    log_debug(f"Field {field_name} marked for review: Low confidence ({field_data.get('confidence', 0.0)})")
        
        # Check if any fields need review
        any_field_needs_review = False
        for field_name, field_data in gemini_fields.items():
            if isinstance(field_data, dict):
                if field_data.get("requires_human_review", False):
                    any_field_needs_review = True
                    log_debug(f"Field {field_name} needs review", field_data)
                    break

        now = datetime.now(timezone.utc).isoformat()
        reviewed_data = {
            "document_id": job_id,
            "fields": gemini_fields,
            "school_id": school_id,
            "user_id": user_id,
            "event_id": event_id,
            "image_path": job.get("image_path"),
            "review_status": "needs_human_review" if any_field_needs_review else "reviewed",
            "created_at": now,
            "updated_at": now
        }
        
        log_debug("=== FINAL REVIEW STATUS ===", {
            "Review Status": "needs_human_review" if any_field_needs_review else "reviewed",
            "Reviewed Data": reviewed_data
        })
        
        upsert_reviewed_data(supabase_client, reviewed_data)
        log_debug(f"✅ Upserted reviewed_data for job {job_id}")
        
        update_processing_job(supabase_client, job_id, {
            "status": "complete",
            "updated_at": now,
            "error_message": None
        })
        log_debug(f"✅ Job {job_id} complete.")
        log_debug("=== PROCESSING JOB END ===\n")
        
    except Exception as e:
        log_debug(f"❌ Error processing job {job_id}: {e}")
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
    log_debug("Starting CardCapture processing worker...")
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
            log_debug(f"Worker error: {e}")
            traceback.print_exc()
            time.sleep(SLEEP_SECONDS)

if __name__ == "__main__":
    main() 