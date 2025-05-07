import os
import time
import tempfile
import traceback
import json
from datetime import datetime, timezone
from supabase import create_client
import mimetypes
import uuid
import googlemaps

# Import your processing functions
from main import get_gemini_review

# === Supabase Client Initialization ===
SUPABASE_URL = os.getenv("SUPABASE_URL")
SUPABASE_KEY = os.getenv("SUPABASE_SERVICE_ROLE_KEY")

supabase_client = create_client(SUPABASE_URL, SUPABASE_KEY)

BUCKET = "cards-uploads"
MAX_RETRIES = 3
SLEEP_SECONDS = 1

# === Google Maps Address Validation Helpers (copied from main.py) ===
GOOGLE_MAPS_API_KEY = os.getenv("GOOGLE_MAPS_API_KEY")
if not GOOGLE_MAPS_API_KEY:
    print("[Address Validation] WARNING: GOOGLE_MAPS_API_KEY is not set. Google Maps validation will be skipped.")
gmaps_client = googlemaps.Client(key=GOOGLE_MAPS_API_KEY) if GOOGLE_MAPS_API_KEY else None

def validate_address_with_google(address: str, zip_code: str):
    if not gmaps_client or not zip_code:
        return None
    full_address_query = f"{address}, {zip_code}" if address else zip_code
    try:
        geocode_result = gmaps_client.geocode(full_address_query)
    except Exception as e:
        return None
    if geocode_result:
        result = geocode_result[0]
        components = result.get('address_components', [])
        street_number = next((c['long_name'] for c in components if 'street_number' in c['types']), None)
        route = next((c['long_name'] for c in components if 'route' in c['types']), None)
        city = next((c['long_name'] for c in components if 'locality' in c['types']), None)
        state = next((c['short_name'] for c in components if 'administrative_area_level_1' in c['types']), None)
        zip_found = next((c['long_name'] for c in components if 'postal_code' in c['types']), None)
        # Compose the street address
        street_address = " ".join(filter(None, [street_number, route]))
        return {
            "address": street_address,
            "city": city,
            "state": state,
            "zip_code": zip_found
        }
    return None

def validate_address_components(address, city, state, zip_code):
    zip_validation = validate_address_with_google("", zip_code)
    validated_city = zip_validation["city"] if zip_validation and zip_validation["city"] else city
    validated_state = zip_validation["state"] if zip_validation and zip_validation["state"] else state
    validated_zip = zip_validation["zip_code"] if zip_validation and zip_validation["zip_code"] else zip_code
    if validated_city and validated_state and validated_zip:
        address_validation = validate_address_with_google(address, validated_zip)
        validated_address = address_validation["address"] if address_validation and address_validation["address"] else address
        validated_city = address_validation["city"] if address_validation and address_validation["city"] else validated_city
        validated_state = address_validation["state"] if address_validation and address_validation["state"] else validated_state
        validated_zip = address_validation["zip_code"] if address_validation and address_validation["zip_code"] else validated_zip
    else:
        validated_address = address
    return {
        "address": validated_address,
        "city": validated_city,
        "state": validated_state,
        "zip_code": validated_zip
    }

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
        # 2. Run Gemini review directly on the image (NO Document AI)
        gemini_result = get_gemini_review({}, tmp_file)
        print(f"Gemini result: {json.dumps(gemini_result)[:200]}...")
        # 3. Address validation using Google Maps
        if gemini_result:
            address = gemini_result.get("address", {}).get("value", "")
            city = gemini_result.get("city", {}).get("value", "")
            state = gemini_result.get("state", {}).get("value", "")
            zip_code = gemini_result.get("zip_code", {}).get("value", "")
            validated = validate_address_components(address, city, state, zip_code)
            # Only print the final validated address and what was used
            if validated:
                if validated["address"] and validated["address"] != address:
                    print(f"[Address Validation] Overwriting Gemini address with validated address: '{validated['address']}'")
                    gemini_result["address"]["value"] = validated["address"]
                else:
                    print(f"[Address Validation] Keeping Gemini address: '{address}'")
                if validated["city"] and validated["city"] != city:
                    print(f"[Address Validation] Overwriting Gemini city with validated city: '{validated['city']}'")
                    gemini_result["city"]["value"] = validated["city"]
                if validated["state"] and validated["state"] != state:
                    print(f"[Address Validation] Overwriting Gemini state with validated state: '{validated['state']}'")
                    gemini_result["state"]["value"] = validated["state"]
                if validated["zip_code"] and validated["zip_code"] != zip_code:
                    print(f"[Address Validation] Overwriting Gemini zip_code with validated zip_code: '{validated['zip_code']}'")
                    gemini_result["zip_code"]["value"] = validated["zip_code"]
                print(f"[Address Validation] Final validated address: '{gemini_result['address']['value']}'")
            else:
                print(f"[Address Validation] Keeping Gemini address: '{address}' (Google Maps validation failed or returned nothing)")
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