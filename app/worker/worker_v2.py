import os
import time
import tempfile
import traceback
import json
from datetime import datetime, timezone
from typing import Dict, Any
import re

from fastapi import FastAPI, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
import uvicorn

# Import new services
from app.services.docai_service import process_image_with_docai
from app.services.settings_service import get_field_requirements, apply_field_requirements, sync_field_requirements
from app.services.review_service import determine_review_status, validate_field_data
from app.services.address_service import validate_and_enhance_address
from app.services.gemini_service import process_card_with_gemini_v2

# Import existing infrastructure
from app.repositories.processing_jobs_repository import update_processing_job
from app.core.clients import supabase_client
from app.repositories.reviewed_data_repository import upsert_reviewed_data
from app.config import DOCAI_PROCESSOR_ID

# Import utils
from app.utils.image_processing import ensure_trimmed_image
from app.utils.storage import upload_to_supabase_storage_from_path

from app.repositories.uploads_repository import (
    update_job_status_with_review
)

BUCKET = "cards-uploads"
MAX_RETRIES = 3
SLEEP_SECONDS = 1

app = FastAPI(title="CardCapture Worker API")

# Add CORS middleware
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # Allow all origins in development
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

@app.get("/")
def root():
    return {"message": "CardCapture Worker API is running"}

def log_worker_debug(message: str, data: Any = None, verbose: bool = False):
    """Write debug message and optional data to worker_v2_debug.log and stdout for Cloud Run."""
    timestamp = datetime.now(timezone.utc).isoformat()
    log_entry = f"\n[{timestamp}] {message}\n"
    # Only print data if verbose is True or if it's a small summary
    if data is not None:
        if verbose:
            if isinstance(data, (dict, list)):
                log_entry += json.dumps(data, indent=2)
            else:
                log_entry += str(data)
            log_entry += "\n"
        else:
            # For dicts/lists, just print keys or summary
            if isinstance(data, dict):
                log_entry += f"Keys: {list(data.keys())}\n"
            elif isinstance(data, list):
                log_entry += f"List length: {len(data)}\n"
            else:
                log_entry += str(data) + "\n"
    # Write to file
    with open('worker_v2_debug.log', 'a') as f:
        f.write(log_entry)
    # Also print to stdout for Cloud Run logging
    print(log_entry, flush=True)

def download_from_supabase(file_url: str, local_path: str) -> None:
    """Download file from Supabase storage to local path"""
    try:
        # Extract bucket and file path from URL
        # Format: "bucket-name/path/to/file.ext"
        url_parts = file_url.split('/', 1)  # Split only on first slash
        if len(url_parts) != 2:
            raise ValueError(f"Invalid file URL format: {file_url}")
            
        bucket_name = url_parts[0]  # "cards-uploads"
        file_path = url_parts[1]    # "user-id/date/filename.ext"
        
        log_worker_debug(f"Downloading from bucket: {bucket_name}, path: {file_path}")
        
        # Download file
        response = supabase_client.storage.from_(bucket_name).download(file_path)
        
        with open(local_path, 'wb') as f:
            f.write(response)
            
        log_worker_debug(f"Downloaded file from {file_url} to {local_path}")
        
    except Exception as e:
        log_worker_debug(f"ERROR downloading file: {str(e)}")
        raise

def split_combined_address_fields(fields: dict) -> dict:
    """
    Detects and splits combined address/city/state/zip fields into separate fields.
    Handles multiple formats:
    - "City, State, Zip"
    - "City, State Zip"
    - "City State Zip"
    - "City, State"
    - "City State"
    """
    for key in ['city_state_zip', 'citystatezip', 'city_state', 'address_line']:
        field = fields.get(key)
        if field and isinstance(field, dict) and field.get('value'):
            value = field['value'].replace('\n', ' ').replace('\r', ' ').strip()
            
            # Pattern 1: City, State, Zip
            match = re.match(r'^([^,]+),\s*([A-Z]{2})(?:,\s*|\s+)(\d{5}(?:-\d{4})?)$', value)
            if match:
                fields['city'] = {'value': match.group(1).strip()}
                fields['state'] = {'value': match.group(2).strip()}
                fields['zip_code'] = {'value': match.group(3).strip()}
                continue

            # Pattern 2: City, State (no zip)
            match = re.match(r'^([^,]+),\s*([A-Z]{2})$', value)
            if match:
                fields['city'] = {'value': match.group(1).strip()}
                fields['state'] = {'value': match.group(2).strip()}
                continue

            # Pattern 3: City State Zip (no commas)
            match = re.match(r'^([^,]+)\s+([A-Z]{2})\s+(\d{5}(?:-\d{4})?)$', value)
            if match:
                fields['city'] = {'value': match.group(1).strip()}
                fields['state'] = {'value': match.group(2).strip()}
                fields['zip_code'] = {'value': match.group(3).strip()}
                continue

            # Pattern 4: City State (no commas, no zip)
            match = re.match(r'^([^,]+)\s+([A-Z]{2})$', value)
            if match:
                fields['city'] = {'value': match.group(1).strip()}
                fields['state'] = {'value': match.group(2).strip()}
                continue

            # If no patterns match, try to extract just city and state
            # This is a fallback for less structured formats
            parts = value.split()
            if len(parts) >= 2:
                # Look for a two-letter state code
                for i in range(len(parts) - 1):
                    if re.match(r'^[A-Z]{2}$', parts[i + 1]):
                        city = ' '.join(parts[:i + 1])
                        state = parts[i + 1]
                        fields['city'] = {'value': city.strip()}
                        fields['state'] = {'value': state.strip()}
                        
                        # If there's a zip code after the state
                        if i + 2 < len(parts) and re.match(r'^\d{5}(?:-\d{4})?$', parts[i + 2]):
                            fields['zip_code'] = {'value': parts[i + 2].strip()}
                        break

    return fields

def prepare_docai_for_review(docai_fields: Dict[str, Any]) -> Dict[str, Any]:
    """
    Prepare DocAI fields for review system when Gemini fails.
    Add required quality indicators so review system doesn't break.
    """
    prepared_fields = {}
    
    for field_name, field_data in docai_fields.items():
        prepared_fields[field_name] = field_data.copy()
        # Add minimal required indicators for review system compatibility
        prepared_fields[field_name].update({
            "edit_made": False,
            "edit_type": "none",
            "original_value": field_data.get("value", ""),
            "text_clarity": "unclear",
            "certainty": "uncertain", 
            "notes": "AI processing failed - showing raw OCR data",
            "review_confidence": field_data.get("confidence", 0.0),
            "requires_human_review": False,
            "review_notes": ""
        })
    
    return prepared_fields

def process_job_v2(job: Dict[str, Any]) -> None:
    """
    Simplified, reliable processing flow with atomic database operations
    """
    job_id = job["id"]
    file_url = job["file_url"]
    user_id = job["user_id"]
    school_id = job["school_id"]
    event_id = job.get("event_id")
    
    log_worker_debug("=== PROCESSING JOB V2 START ===")
    log_worker_debug("Job Details", {
        "Job ID": job_id,
        "User ID": user_id,
        "School ID": school_id,
        "Event ID": event_id,
        "File URL": file_url
    })
    
    tmp_file = None
    try:
        # Step 1: Get school field requirements
        log_worker_debug("=== STEP 1: GET FIELD REQUIREMENTS ===")
        school_query = supabase_client.table("schools").select("docai_processor_id").eq("id", school_id).maybe_single().execute()
        processor_id = school_query.data.get("docai_processor_id") if school_query and school_query.data else DOCAI_PROCESSOR_ID
        log_worker_debug(f"Using DocAI processor: {processor_id}")
        
        field_requirements = get_field_requirements(school_id)
        log_worker_debug("Current Field Requirements", field_requirements, verbose=True)
        
        # Step 2: Download image
        log_worker_debug("=== STEP 2: DOWNLOAD IMAGE ===")
        with tempfile.NamedTemporaryFile(delete=False, suffix=os.path.splitext(file_url)[1] or '.png') as tmp:
            tmp_file = tmp.name
        download_from_supabase(file_url, tmp_file)
        
        # Step 3: Process with DocAI
        log_worker_debug("=== STEP 3: DOCAI PROCESSING ===")
        docai_fields, cropped_image_path = process_image_with_docai(tmp_file, processor_id)
        log_worker_debug("Original DocAI Response", docai_fields, verbose=True)
        
        # Step 4: Split address fields
        log_worker_debug("=== STEP 4: SPLIT ADDRESS FIELDS ===")
        docai_fields = split_combined_address_fields(docai_fields)
        log_worker_debug("Fields After Address Splitting", docai_fields, verbose=True)
        
        # Step 5: Sync fields with school settings
        log_worker_debug("=== STEP 5: SYNC FIELDS WITH SCHOOL SETTINGS ===")
        all_field_names = list(docai_fields.keys())
        updated_requirements = sync_field_requirements(school_id, all_field_names)
        log_worker_debug("Updated Field Requirements", updated_requirements, verbose=True)
        
        # Step 6: Apply requirements to fields
        log_worker_debug("=== STEP 6: APPLY FIELD REQUIREMENTS ===")
        docai_fields = apply_field_requirements(docai_fields, updated_requirements)
        log_worker_debug("Fields After Applying Requirements", docai_fields, verbose=True)
        
        # Step 7: Validate addresses
        log_worker_debug("=== STEP 7: ADDRESS VALIDATION ===")
        validated_fields = validate_and_enhance_address(docai_fields)
        log_worker_debug("Fields After Address Validation", validated_fields, verbose=True)
        
        # Step 8: Fetch valid majors
        log_worker_debug("=== STEP 8: FETCH VALID MAJORS ===")
        majors_query = supabase_client.table("schools").select("majors").eq("id", school_id).maybe_single().execute()
        valid_majors = majors_query.data.get("majors") if majors_query and majors_query.data and majors_query.data.get("majors") else []
        log_worker_debug("Valid majors", valid_majors, verbose=True)
        
        # Step 9: Process with Gemini (with failure handling)
        log_worker_debug("=== STEP 9: GEMINI PROCESSING ===")
        ai_processing_failed = False
        ai_error_message = None
        
        try:
            gemini_fields = process_card_with_gemini_v2(
                cropped_image_path,
                validated_fields,
                valid_majors
            )
            log_worker_debug("Gemini Output", gemini_fields, verbose=True)
            
        except Exception as gemini_error:
            log_worker_debug(f"⚠️ Gemini processing failed: {str(gemini_error)}")
            log_worker_debug("Full Gemini error traceback:", traceback.format_exc())
            
            # Use DocAI fields with proper structure for review system
            gemini_fields = prepare_docai_for_review(validated_fields)
            ai_processing_failed = True
            ai_error_message = str(gemini_error)
            
            log_worker_debug("Using DocAI fallback data", gemini_fields, verbose=True)
        
        # Step 10: Final validation and review determination
        log_worker_debug("=== STEP 10: FINAL VALIDATION ===")
        
        if ai_processing_failed:
            # Set special review status for AI failures
            final_fields = gemini_fields  # Already prepared fallback data
            review_status = "ai_failed"
            fields_needing_review = []
            log_worker_debug("AI Processing Failed - Setting review_status to ai_failed")
        else:
            # Normal processing path
            final_fields = validate_field_data(gemini_fields)
            review_status, fields_needing_review = determine_review_status(final_fields)
            
        log_worker_debug("Final Fields", final_fields, verbose=True)
        log_worker_debug("Review Status", {
            "status": review_status,
            "fields_needing_review": fields_needing_review,
            "ai_processing_failed": ai_processing_failed
        }, verbose=True)
        
        # Step 11: Trim and upload image
        log_worker_debug("=== STEP 11: TRIM AND UPLOAD IMAGE ===")
        trimmed_image_path = ensure_trimmed_image(tmp_file)
        trimmed_storage_path = None
        try:
            trimmed_storage_path = upload_to_supabase_storage_from_path(
                supabase_client,
                trimmed_image_path,
                user_id,
                os.path.basename(trimmed_image_path)
            )
            log_worker_debug(f"Trimmed image uploaded to Supabase: {trimmed_storage_path}")
        except Exception as e:
            log_worker_debug(f"Failed to upload trimmed image to Supabase: {e}")
        
        # Step 12: Update job status and create review data
        log_worker_debug("=== STEP 12: UPDATE JOB STATUS ===")
        now = datetime.now(timezone.utc).isoformat()
        review_data = {
            "document_id": job_id,
            "fields": final_fields,  # Use final_fields which includes all processing
            "school_id": school_id,
            "user_id": user_id,
            "event_id": event_id,
            "image_path": job.get("image_path"),
            "trimmed_image_path": trimmed_storage_path,
            "review_status": review_status,
            "created_at": now,
            "updated_at": now
        }
        
        # Add AI error information if processing failed
        if ai_processing_failed:
            review_data["ai_error_message"] = ai_error_message
        log_worker_debug("Review Data to be Saved", review_data, verbose=True)
        
        update_job_status_with_review(supabase_client, job_id, "complete", review_data)
        
        log_worker_debug(f"✅ Job {job_id} completed successfully")
        log_worker_debug("=== PROCESSING JOB V2 END ===\n")
        
    except Exception as e:
        log_worker_debug(f"❌ Error processing job {job_id}: {str(e)}")
        log_worker_debug("Full traceback", traceback.format_exc())
        
        # Update job status to failed directly  
        now = datetime.now(timezone.utc).isoformat()
        update_processing_job(supabase_client, job_id, {
            "status": "failed",
            "error_message": str(e),
            "updated_at": now
        })
        
        # Clean up temporary files
        if os.path.exists(tmp_file):
            os.remove(tmp_file)
            log_worker_debug(f"Cleaned up temporary file: {tmp_file}")
        
        raise

def main_v2():
    """
    Main worker loop using the new simplified processing pipeline
    """
    log_worker_debug("Starting CardCapture processing worker V2...")
    
    try:
        log_worker_debug("=== CHECKING FOR QUEUED JOBS ===")
        
        # Get next queued job
        jobs = supabase_client.table("processing_jobs").select("*").eq("status", "queued").order("created_at").limit(1).execute()
        
        if jobs.data and len(jobs.data) > 0:
            job = jobs.data[0]
            log_worker_debug(f"Found job {job['id']} to process")
            
            # Mark job as processing
            now = datetime.now(timezone.utc).isoformat()
            update_processing_job(supabase_client, job["id"], {
                "status": "processing",
                "updated_at": now
            })
            
            # Process the job
            process_job_v2(job)
            
        else:
            log_worker_debug("No queued jobs found, sleeping...")
            time.sleep(SLEEP_SECONDS)
            
    except Exception as e:
        log_worker_debug(f"Worker error: {str(e)}")
        log_worker_debug("Worker traceback", traceback.format_exc())
        time.sleep(SLEEP_SECONDS)

@app.post("/process")
async def process_job_endpoint(request: Request):
    try:
        # Log request details
        log_worker_debug("=== INCOMING REQUEST ===")
        log_worker_debug("Headers", dict(request.headers))
        log_worker_debug("Client", request.client)
        
        data = await request.json()
        log_worker_debug("Request body", data)
        
        # Check if job_id is provided
        if not data or "job_id" not in data:
            raise HTTPException(status_code=400, detail="Missing job_id in request")
        
        job_id = data["job_id"]
        log_worker_debug(f"Processing job_id: {job_id}")
        
        # Fetch the job details from Supabase
        job_query = supabase_client.table("processing_jobs").select("*").eq("id", job_id).maybe_single().execute()
        
        if not job_query.data:
            log_worker_debug(f"Job {job_id} not found in database")
            raise HTTPException(status_code=404, detail=f"Job {job_id} not found")
            
        job = job_query.data
        log_worker_debug("Found job in database", job)
        
        # Update status to processing using direct table update
        now = datetime.now(timezone.utc).isoformat()
        update_processing_job(supabase_client, job_id, {
            "status": "processing", 
            "updated_at": now
        })
        
        # Process the job
        process_job_v2(job)
        return {"status": "success", "message": f"Job {job_id} processing started"}
        
    except HTTPException:
        raise
    except Exception as e:
        log_worker_debug(f"Error in process_job_endpoint: {str(e)}")
        log_worker_debug("Full traceback", traceback.format_exc())
        raise HTTPException(status_code=500, detail=str(e))

@app.post("/retry-ai-processing/{document_id}")
async def retry_ai_processing(document_id: str):
    """
    Retry Gemini processing for a card that failed AI processing
    """
    try:
        log_worker_debug(f"=== RETRY AI PROCESSING FOR {document_id} ===")
        
        # Get the reviewed_data record
        review_query = supabase_client.table("reviewed_data").select("*").eq("document_id", document_id).maybe_single().execute()
        if not review_query.data:
            log_worker_debug(f"Card {document_id} not found in reviewed_data")
            raise HTTPException(status_code=404, detail="Card not found")
            
        review_data = review_query.data
        log_worker_debug("Found review data", {
            "document_id": document_id,
            "review_status": review_data.get("review_status"),
            "ai_error_message": review_data.get("ai_error_message")
        })
        
        # Check if this card actually failed AI processing
        if review_data.get("review_status") != "ai_failed":
            log_worker_debug(f"Card {document_id} review_status is {review_data.get('review_status')}, not ai_failed")
            raise HTTPException(status_code=400, detail="This card did not fail AI processing")
            
        # Get what we need for retry
        trimmed_image_path = review_data["trimmed_image_path"]  # Cropped image
        docai_fields = review_data["fields"]  # DocAI fields (stored when AI failed)
        school_id = review_data["school_id"]
        
        log_worker_debug("Retry data extracted", {
            "trimmed_image_path": trimmed_image_path,
            "school_id": school_id,
            "field_count": len(docai_fields)
        })
        
        # Get valid majors for school
        majors_query = supabase_client.table("schools").select("majors").eq("id", school_id).maybe_single().execute()
        valid_majors = majors_query.data.get("majors") if majors_query and majors_query.data else []
        log_worker_debug("Valid majors for retry", valid_majors)
        
        # Download the trimmed image to process with Gemini
        # The trimmed_image_path is a storage path, we need to download it
        with tempfile.NamedTemporaryFile(delete=False, suffix='.jpg') as tmp:
            temp_image_path = tmp.name
        
        try:
            download_from_supabase(trimmed_image_path, temp_image_path)
            log_worker_debug(f"Downloaded trimmed image for retry: {temp_image_path}")
            
            # Retry Gemini processing
            log_worker_debug("Retrying Gemini processing...")
            gemini_fields = process_card_with_gemini_v2(
                temp_image_path,    # Downloaded cropped image
                docai_fields,       # Original DocAI fields 
                valid_majors
            )
            log_worker_debug("Retry Gemini processing successful", verbose=True)
            
            # Determine new review status with successful Gemini data
            final_fields = validate_field_data(gemini_fields)
            new_review_status, fields_needing_review = determine_review_status(final_fields)
            
            log_worker_debug("New review status after retry", {
                "status": new_review_status,
                "fields_needing_review": fields_needing_review
            })
            
            # Update reviewed_data with successful results
            now = datetime.now(timezone.utc).isoformat()
            update_result = supabase_client.table("reviewed_data").update({
                "fields": final_fields,               # Now has proper Gemini data
                "review_status": new_review_status,   # Proper review status
                "ai_error_message": None,            # Clear the error
                "updated_at": now
            }).eq("document_id", document_id).execute()
            
            log_worker_debug("Updated reviewed_data successfully")
            
            return {
                "status": "success", 
                "message": "AI processing retry completed successfully",
                "new_review_status": new_review_status,
                "fields_updated": len(final_fields)
            }
            
        finally:
            # Clean up temporary image file
            if os.path.exists(temp_image_path):
                os.remove(temp_image_path)
                log_worker_debug(f"Cleaned up temporary retry image: {temp_image_path}")
        
    except HTTPException:
        raise
    except Exception as e:
        log_worker_debug(f"Error retrying AI processing for {document_id}: {str(e)}")
        log_worker_debug("Full retry error traceback:", traceback.format_exc())
        raise HTTPException(status_code=500, detail=f"Retry failed: {str(e)}")


if __name__ == "__main__":
    port = int(os.environ.get("PORT", 8080))
    uvicorn.run(app, host="0.0.0.0", port=port) 