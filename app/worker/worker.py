import os
import time
import tempfile
import traceback
import json
from datetime import datetime, timezone
from app.services.document_service import parse_card_with_gemini, validate_address_with_google
from app.services.uploads_service import process_image_and_trim
# from app.services.gemini_service import run_gemini_review
from app.repositories.processing_jobs_repository import update_processing_job
from app.core.clients import supabase_client
from app.repositories.uploads_repository import insert_extracted_data_db
from app.repositories.reviewed_data_repository import upsert_reviewed_data
from app.repositories.upload_notifications_repository import insert_upload_notification
from app.config import DOCAI_PROCESSOR_ID

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
        
        # Fetch school's DocAI processor ID
        school_query = supabase_client.table("schools").select("docai_processor_id").eq("id", school_id).maybe_single().execute()
        processor_id = school_query.data.get("docai_processor_id") if school_query and school_query.data else DOCAI_PROCESSOR_ID
        log_debug(f"Using DocAI processor: {processor_id}")
        
        # Process with DocAI
        docai_json, trimmed_path = process_image_and_trim(tmp_file, processor_id)
        if not docai_json:
            raise Exception("No DocAI fields returned from processing")
        log_debug("=== DOCAI FIELDS FROM PROCESSING ===", docai_json)
        
        # Sync preferences before processing
        log_debug("=== SYNCING CARD FIELD PREFERENCES ===")
        sync_card_fields_preferences(supabase_client, user_id, school_id, docai_json)
        
        # Get the latest school settings
        log_debug("=== RETRIEVING SCHOOL SETTINGS ===")
        school_query = supabase_client.table("schools").select("card_fields").eq("id", school_id).maybe_single().execute()
        if school_query and school_query.data:
            card_fields = school_query.data.get("card_fields", {})
            log_debug("School settings", card_fields)
            
            # Update DocAI fields with required flags
            log_debug("=== UPDATING FIELDS WITH REQUIRED FLAGS ===")
            for field_name, field_data in docai_json.items():
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
            
            # Check for missing required fields and add them as empty
            log_debug("=== CHECKING FOR MISSING REQUIRED FIELDS ===")
            for field_name, field_settings in card_fields.items():
                if field_settings.get("required", False) and field_name not in docai_json:
                    log_debug(f"Adding missing required field: {field_name}")
                    docai_json[field_name] = {
                        "value": "",
                        "confidence": 0.0,
                        "bounding_box": [],
                        "required": True,
                        "enabled": True,
                        "requires_human_review": True,
                        "review_notes": "Required field not detected by DocAI",
                        "source": "missing_required"
                    }
        
        # Debug logging for DocAI fields after updates
        log_debug("=== UPDATED DOCAI FIELDS ===", docai_json)
        
        # Validate address components
        address = docai_json.get('address', {}).get('value', '')
        city = docai_json.get('city', {}).get('value', '')
        state = docai_json.get('state', {}).get('value', '')
        zip_code = docai_json.get('zip_code', {}).get('value', '')
        
        log_debug("=== VALIDATING ADDRESS ===", {
            "Address": address,
            "City": city,
            "State": state,
            "Zip Code": zip_code
        })
        
        # Always attempt address validation
        validation_result = validate_address_with_google(address, zip_code)
        if validation_result:
            log_debug("Address validation result", validation_result)
            # Add city and state from validation
            docai_json['city'] = {
                "value": validation_result['city'],
                "confidence": 0.95,
                "source": "zip_validation"
            }
            docai_json['state'] = {
                "value": validation_result['state'],
                "confidence": 0.95,
                "source": "zip_validation"
            }
            # Update address with validated street address, but preserve original if empty
            if validation_result['street_address']:
                docai_json['address'] = {
                    "value": validation_result['street_address'],
                    "confidence": 0.95,
                    "source": "address_validation"
                }
                log_debug(f"Updated address to: {validation_result['street_address']}")
            else:
                # Keep original address if Google returns empty street address
                docai_json['address'] = {
                    "value": address,  # Original address
                    "confidence": 0.7,  # Lower confidence since we couldn't validate it
                    "source": "original",
                    "requires_human_review": True,
                    "review_notes": "Address could not be validated but city/state were found from zip"
                }
                log_debug(f"Preserved original address: {address} (Google returned empty street address)")
            log_debug(f"Added city: {validation_result['city']} and state: {validation_result['state']} from zip validation")
        else:
            # Mark address-related fields for review if validation fails
            if not address:
                docai_json['address'] = {
                    "value": "",
                    "confidence": 0.0,
                    "requires_human_review": True,
                    "review_notes": "Missing address",
                    "source": "validation_failed"
                }
            if not city:
                docai_json['city'] = {
                    "value": "",
                    "confidence": 0.0,
                    "requires_human_review": True,
                    "review_notes": "Missing city",
                    "source": "validation_failed"
                }
            if not state:
                docai_json['state'] = {
                    "value": "",
                    "confidence": 0.0,
                    "requires_human_review": True,
                    "review_notes": "Missing state",
                    "source": "validation_failed"
                }
            log_debug("Address validation failed - marked fields for review")
        
        # Run Gemini enhancement
        log_debug("=== RUNNING GEMINI ENHANCEMENT ===")
        gemini_fields = parse_card_with_gemini(tmp_file, docai_json)
        
        # Ensure required flags are preserved and check for empty required fields
        log_debug("=== FINALIZING FIELD DATA ===")
        for field_name, field_data in gemini_fields.items():
            if field_name in docai_json:
                field_data["required"] = docai_json[field_name].get("required", False)
                field_data["enabled"] = docai_json[field_name].get("enabled", True)
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
        log_debug("=== REVIEW STATUS DETERMINATION ===")

        # First check for any fields marked for review
        fields_needing_review = [f for f, d in gemini_fields.items() 
                               if isinstance(d, dict) and d.get("requires_human_review")]
        log_debug("Fields marked for review", fields_needing_review)

        # If any fields are marked for review, set needs_review to true
        if fields_needing_review:
            any_field_needs_review = True
            log_debug(f"Fields marked for review: {fields_needing_review}")
        else:
            # Only check required fields if no fields are explicitly marked for review
            required_fields = [field_name for field_name, field_data in gemini_fields.items() 
                             if isinstance(field_data, dict) and field_data.get("required", False)]
            log_debug("Required fields", required_fields)

            for field_name in required_fields:
                if field_name not in gemini_fields:
                    any_field_needs_review = True
                    log_debug(f"Field {field_name} is required but missing")
                    break
                field_data = gemini_fields[field_name]
                if not field_data.get("value"):
                    any_field_needs_review = True
                    field_data["requires_human_review"] = True
                    field_data["review_notes"] = "Required field is missing"
                    log_debug(f"Field {field_name} marked for review: Required field is missing")
                    break
                if field_data.get("confidence", 0.0) < 0.7:
                    any_field_needs_review = True
                    field_data["requires_human_review"] = True
                    field_data["review_notes"] = "Required field has low confidence"
                    log_debug(f"Field {field_name} marked for review: Low confidence ({field_data.get('confidence', 0.0)})")
                    break

        # Set the final review status
        if any_field_needs_review:
            review_status = "needs_human_review"
            log_debug("Setting review status to needs_human_review")
        else:
            review_status = "reviewed"
            log_debug("Setting review status to reviewed")

        now = datetime.now(timezone.utc).isoformat()
        reviewed_data = {
            "document_id": job_id,
            "fields": gemini_fields,
            "school_id": school_id,
            "user_id": user_id,
            "event_id": event_id,
            "image_path": job.get("image_path"),
            "review_status": review_status,
            "created_at": now,
            "updated_at": now
        }
        
        log_debug("=== SAVING REVIEWED DATA ===")
        log_debug(f"Document ID: {job_id}")
        log_debug(f"Review Status: {review_status}")
        log_debug(f"Fields requiring review: {[f for f, d in gemini_fields.items() if isinstance(d, dict) and d.get('requires_human_review')]}")

        upsert_reviewed_data(supabase_client, reviewed_data)
        log_debug(f"✅ Upserted reviewed_data for job {job_id}")
        
        update_processing_job(supabase_client, job_id, {
            "status": "complete",
            "updated_at": now,
            "error_message": None,
            "result_json": gemini_fields  # Add the result_json here
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
            log_debug("=== CHECKING FOR QUEUED JOBS ===")
            jobs = supabase_client.table("processing_jobs").select("*").eq("status", "queued").order("created_at").limit(1).execute()
            log_debug(f"Found {len(jobs.data) if jobs.data else 0} queued jobs")
            
            if jobs.data and len(jobs.data) > 0:
                job = jobs.data[0]
                log_debug(f"Processing job {job['id']}")
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