import os
import tempfile
import uuid
from app.core.clients import supabase_client
from app.utils.storage import upload_to_supabase_storage_from_path
from app.repositories.uploads_repository import insert_processing_job_db, insert_extracted_data_db
from datetime import datetime, timezone
from trim_card import trim_card
from .pdf_split import split_pdf_to_pngs
from PIL import Image

async def bulk_upload_service(background_tasks, file, event_id, school_id, user):
    user_id = user['id']
    if not supabase_client:
        return {"error": "Database client not available"}

    # Save uploaded file to a temp location
    with tempfile.NamedTemporaryFile(delete=False, suffix=os.path.splitext(file.filename)[1]) as temp_file:
        temp_file.write(await file.read())
        temp_file_path = temp_file.name

    jobs_created = []
    try:
        # Check if file is a PDF
        if file.filename.lower().endswith('.pdf'):
            print(f"[DEBUG] Entering PDF processing block for file: {file.filename}")
            with tempfile.TemporaryDirectory() as tmpdir:
                # Split PDF into PNGs immediately after saving
                png_paths = split_pdf_to_pngs(temp_file_path, tmpdir)
                print(f"[DEBUG] split_pdf_to_pngs returned {len(png_paths)} images: {png_paths}")
                if not png_paths:
                    print(f"[ERROR] No PNGs were generated from PDF: {temp_file_path}")
                    return {"error": "Failed to split PDF into images."}
                for png_path in png_paths:
                    # Trim the image
                    trimmed_path = trim_card(png_path, png_path, pad=20)
                    # Ensure image is RGB for compatibility
                    with Image.open(trimmed_path) as img:
                        if img.mode != "RGB":
                            img = img.convert("RGB")
                            img.save(trimmed_path)
                    # Upload to Supabase storage
                    storage_path = upload_to_supabase_storage_from_path(supabase_client, trimmed_path, user_id, os.path.basename(trimmed_path))
                    image_path_for_db = storage_path.replace('cards-uploads/', '') if storage_path.startswith('cards-uploads/') else storage_path
                    # Create processing job
                    job_id = str(uuid.uuid4())
                    now = datetime.now(timezone.utc).isoformat()
                    job_data = {
                        "id": job_id,
                        "user_id": user_id,
                        "school_id": school_id,
                        "file_url": storage_path,
                        "image_path": image_path_for_db,
                        "status": "queued",
                        "result_json": None,
                        "error_message": None,
                        "created_at": now,
                        "updated_at": now,
                        "event_id": event_id
                    }
                    supabase_client.table("processing_jobs").insert(job_data).execute()
                    # Insert into extracted_data
                    document_id = str(uuid.uuid4())
                    insert_data = {
                        "document_id": document_id,
                        "fields": {},
                        "image_path": storage_path,
                        "event_id": event_id,
                        "school_id": school_id
                    }
                    supabase_client.table("extracted_data").insert(insert_data).execute()
                    jobs_created.append({"job_id": job_id, "document_id": document_id, "image": storage_path})
        else:
            return {"error": "File is not a PDF. Use the standard upload for images."}
    finally:
        # Cleanup temp file
        if os.path.exists(temp_file_path):
            os.remove(temp_file_path)
    return {"status": "success", "jobs_created": jobs_created} 