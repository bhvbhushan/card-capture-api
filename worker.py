import os
import time
import tempfile
import traceback
import json
from datetime import datetime, timezone
from supabase import create_client
import mimetypes
import uuid

# Import your processing functions
from main import process_image, get_gemini_review

# === Supabase Client Initialization ===
SUPABASE_URL = os.getenv("SUPABASE_URL")
SUPABASE_KEY = os.getenv("SUPABASE_SERVICE_ROLE_KEY")

supabase_client = create_client(SUPABASE_URL, SUPABASE_KEY)

BUCKET = "cards-uploads"
MAX_RETRIES = 3
SLEEP_SECONDS = 1

# === Helper: Download file from Supabase Storage ===
def download_from_supabase(storage_path, local_path):
    res = supabase_client.storage.from_(BUCKET).download(storage_path.replace(f"{BUCKET}/", ""))
    if hasattr(res, 'error') and res.error:
        raise Exception(f"Supabase Storage download error: {res.error}")
    with open(local_path, "wb") as f:
        f.write(res)
    return local_path

# === Worker Loop ===
def process_job(job):
    job_id = job["id"]
    file_url = job["file_url"]
    user_id = job["user_id"]
    school_id = job["school_id"]
    event_id = job.get("event_id")
    print(f"Processing job {job_id} for user {user_id}, file {file_url}")
    tmp_file = None
    try:
        # 1. Download image from Supabase Storage
        with tempfile.NamedTemporaryFile(delete=False, suffix=os.path.splitext(file_url)[1] or '.png') as tmp:
            tmp_file = tmp.name
        download_from_supabase(file_url, tmp_file)
        print(f"Downloaded to {tmp_file}")
        # 2. Run Document AI pipeline
        extracted_fields = process_image(tmp_file)
        print(f"Extracted fields: {json.dumps(extracted_fields)[:200]}...")
        # 3. Run Gemini review
        gemini_result = get_gemini_review(extracted_fields, tmp_file)
        print(f"Gemini result: {json.dumps(gemini_result)[:200]}...")
        # 4. Update job as complete
        now = datetime.now(timezone.utc).isoformat()
        supabase_client.table("processing_jobs").update({
            "status": "complete",
            "result_json": gemini_result,
            "updated_at": now,
            "error_message": None
        }).eq("id", job_id).execute()
        print(f"Job {job_id} complete.")
        # 5. Upsert into reviewed_data for frontend
        supabase_client.table("reviewed_data").upsert({
            "document_id": job_id,
            "fields": gemini_result,
            "school_id": school_id,
            "user_id": user_id,
            "event_id": event_id,
            "image_path": job.get("image_path"),
            "review_status": "reviewed",
            "created_at": now,
            "updated_at": now
        }, on_conflict="document_id").execute()
        print(f"reviewed_data upserted for job {job_id}.")
    except Exception as e:
        print(f"Error processing job {job_id}: {e}")
        traceback.print_exc()
        # Retry logic
        retries = job.get("retries", 0) + 1
        now = datetime.now(timezone.utc).isoformat()
        if retries < MAX_RETRIES:
            supabase_client.table("processing_jobs").update({
                "status": "queued",
                "error_message": str(e),
                "updated_at": now,
                "retries": retries
            }).eq("id", job_id).execute()
            print(f"Job {job_id} re-queued (retry {retries}).")
        else:
            supabase_client.table("processing_jobs").update({
                "status": "failed",
                "error_message": str(e),
                "updated_at": now
            }).eq("id", job_id).execute()
            print(f"Job {job_id} failed after {MAX_RETRIES} retries.")
    finally:
        if tmp_file and os.path.exists(tmp_file):
            os.remove(tmp_file)


def main():
    print("Starting CardCapture processing worker...")
    while True:
        try:
            # Poll for queued jobs
            jobs = supabase_client.table("processing_jobs").select("*").eq("status", "queued").order("created_at").limit(1).execute()
            if jobs.data and len(jobs.data) > 0:
                job = jobs.data[0]
                # Mark as processing
                now = datetime.now(timezone.utc).isoformat()
                supabase_client.table("processing_jobs").update({
                    "status": "processing",
                    "updated_at": now
                }).eq("id", job["id"]).execute()
                process_job(job)
            else:
                time.sleep(SLEEP_SECONDS)
        except Exception as e:
            print(f"Worker error: {e}")
            traceback.print_exc()
            time.sleep(SLEEP_SECONDS)

if __name__ == "__main__":
    main() 