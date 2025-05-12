import os
import shutil
import tempfile
import uuid
from fastapi.responses import JSONResponse, FileResponse
from app.core.clients import supabase_client
from app.utils.image_processing import ensure_trimmed_image
from app.utils.storage import upload_to_supabase_storage_from_path
from app.core.clients import supabase_client, docai_client
from app.repositories.uploads_repository import (
    insert_processing_job_db,
    insert_extracted_data_db,
    insert_upload_notification_db,
    select_upload_notification_db,
    select_extracted_data_image_db
)
# from app.services.document_service import process_image
from app.services.document_service import parse_card_with_gemini
from app.services.gemini_service import run_gemini_review

async def upload_file_service(background_tasks, file, event_id, school_id, user):
    print(f"📤 Received upload request for file: {file.filename}")
    print(f"📤 File content type: {file.content_type}")
    print(f"📤 File size: {file.size if hasattr(file, 'size') else 'unknown'}")
    print(f"📤 Event ID: {event_id}")
    user_id = user['id']
    if not supabase_client:
        print("❌ Database client not available")
        return JSONResponse(status_code=503, content={"error": "Database client not available."})
    try:
        with tempfile.NamedTemporaryFile(delete=False, suffix=os.path.splitext(file.filename)[1] or '.png') as temp_file:
            shutil.copyfileobj(file.file, temp_file)
            temp_path = temp_file.name
        print(f"📄 File saved temporarily to: {temp_path}")
        trimmed_path = ensure_trimmed_image(temp_path)
        print(f"✂️ Trimmed image saved to: {trimmed_path}")
        storage_path = upload_to_supabase_storage_from_path(supabase_client, trimmed_path, user_id, file.filename)
        print(f"✅ Uploaded trimmed image to Supabase Storage: {storage_path}")
        try:
            os.remove(temp_path)
            if trimmed_path != temp_path:
                os.remove(trimmed_path)
            print(f"🗑️ Temp files deleted.")
        except Exception as cleanup_e:
            print(f"⚠️ Error deleting temp files: {cleanup_e}")
        job_id = str(uuid.uuid4())
        from datetime import datetime, timezone
        now = datetime.now(timezone.utc).isoformat()
        image_path_for_db = storage_path.replace('cards-uploads/', '') if storage_path.startswith('cards-uploads/') else storage_path
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
        insert_processing_job_db(supabase_client, job_data)
        # Insert empty extracted_data row with document_id = job_id (legacy 1:1 mapping)
        insert_data = {
            "document_id": job_id,
            "fields": {},  # Will be filled after processing
            "image_path": storage_path,
            "event_id": event_id,
            "school_id": school_id
        }
        try:
            # extracted_fields = process_image(trimmed_path)
            extracted_fields = parse_card_with_gemini(trimmed_path)
            insert_extracted_data_db(supabase_client, insert_data)
            print(f"✅ Saved initial data for {job_id} (document_id)")
        except Exception as db_error:
            print(f"⚠️ Database error inserting extracted_data: {db_error}")
        # Schedule background processing (worker will handle extraction and review)
        response_data = {
            "status": "success",
            "message": "File uploaded and trimmed successfully. Processing will continue in the background.",
            "job_id": job_id,
            "document_id": job_id,
            "storage_path": storage_path
        }
        return JSONResponse(status_code=200, content=response_data)
    except Exception as e:
        print(f"❌ Error uploading or processing file: {e}")
        import traceback
        traceback.print_exc()
        return JSONResponse(status_code=500, content={"error": "Failed to upload or process file."})

async def check_upload_status_service(document_id: str):
    if not supabase_client:
        return JSONResponse(status_code=503, content={"error": "Database client not available."})
    try:
        response = select_upload_notification_db(supabase_client, document_id)
        if response.data and len(response.data) > 0:
            return JSONResponse(content=response.data[0])
        else:
            return JSONResponse(content={"status": "not_found"})
    except Exception as e:
        print(f"❌ Error checking upload status: {e}")
        import traceback
        traceback.print_exc()
        return JSONResponse(status_code=500, content={"error": "Failed to check upload status."})

async def get_image_service(document_id: str):
    if not supabase_client:
        return JSONResponse(status_code=503, content={"error": "Database client not available."})
    print(f"🖼️ Image requested for document_id: {document_id}")
    try:
        response = select_extracted_data_image_db(supabase_client, document_id)
        if response.data:
            image_path = response.data.get("trimmed_image_path") or response.data.get("image_path")
            print(f"  -> Found image path: {image_path}")
            if image_path and os.path.exists(image_path):
                headers = {
                    "Access-Control-Allow-Origin": "*",
                    "Access-Control-Allow-Methods": "GET, OPTIONS",
                    "Access-Control-Allow-Headers": "*",
                }
                return FileResponse(image_path, headers=headers)
            else:
                print(f"  -> File not found at path: {image_path}")
                return JSONResponse(status_code=404, content={"error": "Image file not found on server."})
        else:
            print(f"  -> No database record found for document_id: {document_id}")
            return JSONResponse(status_code=404, content={"error": "Image record not found."})
    except Exception as e:
        print(f"❌ Error retrieving image for {document_id}: {e}")
        import traceback
        traceback.print_exc()
        return JSONResponse(status_code=500, content={"error": "Failed to retrieve image."}) 