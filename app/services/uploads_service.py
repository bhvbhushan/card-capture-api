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
from trim_card import trim_card
from PIL import Image

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

async def bulk_upload_service(background_tasks, file, event_id, school_id, user):
    user_id = user['id']
    if not supabase_client:
        return {"error": "Database client not available"}

    # Save uploaded file to a temp location
    import tempfile, os, uuid
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
                    # Create processing job and extracted_data with the same ID
                    job_id = str(uuid.uuid4())
                    from datetime import datetime, timezone
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
                    insert_processing_job_db(supabase_client, job_data)
                    # Insert into extracted_data with the SAME job_id
                    insert_data = {
                        "document_id": job_id,
                        "fields": {},
                        "image_path": storage_path,
                        "event_id": event_id,
                        "school_id": school_id
                    }
                    insert_extracted_data_db(supabase_client, insert_data)
                    jobs_created.append({"job_id": job_id, "document_id": job_id, "image": storage_path})
        else:
            return {"error": "File is not a PDF. Use the standard upload for images."}
    finally:
        # Cleanup temp file
        if os.path.exists(temp_file_path):
            os.remove(temp_file_path)
    return {"status": "success", "jobs_created": jobs_created}

def split_pdf_to_pngs(pdf_path, output_dir):
    """
    Splits a PDF into individual PNG images, one per page.
    Args:
        pdf_path (str): Path to the PDF file.
        output_dir (str): Directory to save PNG images.
    Returns:
        List[str]: List of file paths to the generated PNG images.
    """
    from pdf2image import convert_from_path
    import os
    try:
        images = convert_from_path(pdf_path)
        png_paths = []
        for i, image in enumerate(images):
            png_path = os.path.join(output_dir, f"page_{i+1}.png")
            image.save(png_path, 'PNG')
            png_paths.append(png_path)
        return png_paths
    except Exception as e:
        print(f"❌ Error splitting PDF {pdf_path}: {e}")
        return [] 