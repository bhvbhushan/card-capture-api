import os
import time
import tempfile
import traceback
import json
from datetime import datetime, timezone
from app.services.document_service import process_image
from app.services.gemini_service import run_gemini_review
from app.repositories.processing_jobs_repository import update_processing_job
from app.core.clients import supabase_client
from app.repositories.uploads_repository import insert_extracted_data_db

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
        extracted_fields = process_image(tmp_file)
        print(f"Extracted fields: {json.dumps(extracted_fields)[:200]}...")
        # Update extracted fields in extracted_data table before Gemini review
        supabase_client.table("extracted_data").update({"fields": extracted_fields}).eq("document_id", job_id).execute()
        print(f"Updated extracted data for document_id: {job_id}")
        run_gemini_review(job_id, extracted_fields, tmp_file)
        now = datetime.now(timezone.utc).isoformat()
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