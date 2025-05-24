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
from PIL import Image
import csv
from sftp_utils import upload_to_slate
import io
from google.cloud import documentai_v1 as documentai
from app.config import PROJECT_ID, DOCAI_LOCATION, DOCAI_PROCESSOR_ID, TRIMMED_FOLDER
import json
from datetime import datetime, timezone

def process_image_and_trim(input_path: str, processor_id: str, percent_expand: float = 0.5):
    """
    Calls DocAI on the image, extracts field values and bounding box coordinates, trims the image,
    and returns (docai_json, trimmed_image_path).
    """
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

    log_debug("\n=== INITIAL DOCAI PROCESSING START ===")
    log_debug(f"Processing image: {input_path}")
    
    # Set up Document AI client
    client = documentai.DocumentProcessorServiceClient()
    name = f"projects/{PROJECT_ID}/locations/{DOCAI_LOCATION}/processors/{processor_id}"
    log_debug(f"Using DocAI processor: {name}")
    
    with open(input_path, "rb") as image_file:
        image_content = image_file.read()
    raw_document = documentai.RawDocument(content=image_content, mime_type="image/jpeg")
    request = documentai.ProcessRequest(name=name, raw_document=raw_document)
    
    log_debug("Sending request to DocAI...")
    result = client.process_document(request=request)
    document = result.document
    
    log_debug("=== DOCAI RAW RESPONSE ===")
    log_debug("Document text", document.text[:200])  # First 200 chars
    log_debug("Document metadata", {
        "Number of pages": len(document.pages),
        "Number of entities": len(document.entities)
    })
    
    # Gather all bounding box vertices from entities
    all_vertices = []
    field_data = {}
    
    log_debug("=== DETECTED ENTITIES ===")
    for entity in getattr(document, "entities", []):
        entity_data = {
            "Type": entity.type_,
            "Mention Text": entity.mention_text,
            "Confidence": entity.confidence
        }
        
        coords = []
        if entity.page_anchor and entity.page_anchor.page_refs:
            for page_ref in entity.page_anchor.page_refs:
                page_index = page_ref.page
                page = document.pages[page_index]
                width = page.dimension.width
                height = page.dimension.height
                if page_ref.bounding_poly.normalized_vertices:
                    for v in page_ref.bounding_poly.normalized_vertices:
                        pixel_x = v.x * width
                        pixel_y = v.y * height
                        coords.append((pixel_x, pixel_y))
                        all_vertices.append((pixel_x, pixel_y))
                elif page_ref.bounding_poly.vertices:
                    for v in page_ref.bounding_poly.vertices:
                        coords.append((v.x, v.y))
                        all_vertices.append((v.x, v.y))
        
        entity_data["Bounding Box Coordinates"] = coords
        log_debug(f"Entity: {entity.type_}", entity_data)
        
        field_data[entity.type_] = {
            "value": entity.mention_text.strip(),
            "confidence": entity.confidence,
            "bounding_box": coords
        }
    
    log_debug("=== PROCESSED FIELD DATA ===", field_data)
    
    if not all_vertices:
        log_debug("⚠️ No bounding box vertices found for any entity. Returning original image.")
        return field_data, input_path
        
    xs, ys = zip(*all_vertices)
    min_x, max_x = min(xs), max(xs)
    min_y, max_y = min(ys), max(ys)
    
    log_debug("=== IMAGE CROPPING INFO ===", {
        "Original dimensions": Image.open(input_path).size,
        "Bounding box": f"({min_x}, {min_y}) to ({max_x}, {max_y})"
    })
    
    # Crop with percent expansion
    img = Image.open(input_path)
    box_width = max_x - min_x
    box_height = max_y - min_y
    expand_x = box_width * (percent_expand / 2)
    expand_y = box_height * (percent_expand / 2)
    left = max(int(min_x - expand_x), 0)
    top = max(int(min_y - expand_y), 0)
    right = min(int(max_x + expand_x), img.width)
    bottom = min(int(max_y + expand_y), img.height)
    
    log_debug("Expanded box coordinates", {
        "Left": left,
        "Top": top,
        "Right": right,
        "Bottom": bottom
    })
    
    cropped_img = img.crop((left, top, right, bottom))
    filename = os.path.basename(input_path)
    name, ext = os.path.splitext(filename)
    output_path = os.path.join(TRIMMED_FOLDER, f"{name}_trimmed{ext}")
    os.makedirs(os.path.dirname(output_path), exist_ok=True)
    cropped_img.save(output_path)
    
    log_debug("=== CROPPED IMAGE INFO ===", {
        "Saved to": output_path,
        "Dimensions": cropped_img.size
    })
    log_debug("=== INITIAL DOCAI PROCESSING END ===\n")
    
    return field_data, output_path

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
        # Fetch docai_processor_id from schools table (if needed)
        processor_id = DOCAI_PROCESSOR_ID
        # If you want to fetch per-school, add logic here
        docai_json, trimmed_path = process_image_and_trim(temp_path, processor_id)
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
            "result_json": docai_json,
            "error_message": None,
            "created_at": now,
            "updated_at": now,
            "event_id": event_id
        }
        insert_processing_job_db(supabase_client, job_data)
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
                    # Process with DocAI and trim
                    processor_id = DOCAI_PROCESSOR_ID
                    docai_json, trimmed_path = process_image_and_trim(png_path, processor_id)
                    # Upload to Supabase storage
                    storage_path = upload_to_supabase_storage_from_path(supabase_client, trimmed_path, user_id, os.path.basename(trimmed_path))
                    image_path_for_db = storage_path.replace('cards-uploads/', '') if storage_path.startswith('cards-uploads/') else storage_path
                    # Create processing job with DocAI JSON
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
                        "result_json": docai_json,
                        "error_message": None,
                        "created_at": now,
                        "updated_at": now,
                        "event_id": event_id
                    }
                    insert_processing_job_db(supabase_client, job_data)
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

async def export_to_slate_service(payload: dict):
    try:
        school_id = payload.get("school_id")
        rows = payload.get("rows")
        if not school_id or not rows or not isinstance(rows, list):
            return JSONResponse(status_code=400, content={"error": "Missing or invalid school_id or rows."})
        
        # 1. Look up SFTP config
        sftp_resp = supabase_client.table("sftp_configs").select("*").eq("school_id", school_id).maybe_single().execute()
        sftp_config = sftp_resp.data if sftp_resp and sftp_resp.data else None
        if not sftp_config or not sftp_config.get("enabled"):
            return JSONResponse(status_code=400, content={"error": "No SFTP config found or integration is disabled."})
        
        # 2. Generate CSV file from rows
        import tempfile
        import os
        from datetime import datetime, timezone
        
        # Define headers in the same order as the frontend
        headers = [
            "Event Name",
            "First Name",
            "Last Name",
            "Preferred Name",
            "Birthday",
            "Email",
            "Phone Number",
            "Permission to Text",
            "Address",
            "City",
            "State",
            "Zip Code",
            "High School",
            "Class Rank",
            "Students in Class",
            "GPA",
            "Student Type",
            "Entry Term",
            "Major"
        ]
        
        # Define field mappings
        field_mappings = {
            "Event Name": lambda row: row.get("event_name", ""),
            "First Name": lambda row: row.get("fields", {}).get("name", {}).get("value", "").split()[0] if row.get("fields", {}).get("name", {}).get("value") else "",
            "Last Name": lambda row: " ".join(row.get("fields", {}).get("name", {}).get("value", "").split()[1:]) if row.get("fields", {}).get("name", {}).get("value") else "",
            "Preferred Name": lambda row: row.get("fields", {}).get("preferred_first_name", {}).get("value", ""),
            "Birthday": lambda row: row.get("fields", {}).get("date_of_birth", {}).get("value", ""),
            "Email": lambda row: row.get("fields", {}).get("email", {}).get("value", ""),
            "Phone Number": lambda row: row.get("fields", {}).get("cell", {}).get("value", ""),
            "Permission to Text": lambda row: row.get("fields", {}).get("permission_to_text", {}).get("value", ""),
            "Address": lambda row: row.get("fields", {}).get("address", {}).get("value", ""),
            "City": lambda row: row.get("fields", {}).get("city", {}).get("value", ""),
            "State": lambda row: row.get("fields", {}).get("state", {}).get("value", ""),
            "Zip Code": lambda row: row.get("fields", {}).get("zip_code", {}).get("value", ""),
            "High School": lambda row: row.get("fields", {}).get("high_school", {}).get("value", ""),
            "Class Rank": lambda row: row.get("fields", {}).get("class_rank", {}).get("value", ""),
            "Students in Class": lambda row: row.get("fields", {}).get("students_in_class", {}).get("value", ""),
            "GPA": lambda row: row.get("fields", {}).get("gpa", {}).get("value", ""),
            "Student Type": lambda row: row.get("fields", {}).get("student_type", {}).get("value", ""),
            "Entry Term": lambda row: row.get("fields", {}).get("entry_term", {}).get("value", ""),
            "Major": lambda row: row.get("fields", {}).get("major", {}).get("value", "")
        }
        
        # Create CSV content
        csv_content = []
        csv_content.append(headers)  # Add headers
        for row in rows:
            csv_row = [field_mappings[header](row) for header in headers]
            csv_content.append(csv_row)
        
        # Create temporary CSV file
        with tempfile.NamedTemporaryFile(delete=False, suffix=".csv", mode="w", newline="") as tmp_csv:
            writer = csv.writer(tmp_csv)
            writer.writerows(csv_content)
            csv_path = tmp_csv.name

        # DEBUG MODE: Save CSV to downloads folder instead of sending to Slate
        import shutil
        from pathlib import Path
        downloads_path = str(Path.home() / "Downloads")
        debug_csv_path = os.path.join(downloads_path, f"slate_export_debug_{datetime.now().strftime('%Y%m%d_%H%M%S')}.csv")
        shutil.copy2(csv_path, debug_csv_path)
        print(f"DEBUG: CSV saved to {debug_csv_path}")
        
        # Comment out SFTP upload for debugging
        """
        # 3. Upload to SFTP
        class ConfigObj:
            pass
        config_obj = ConfigObj()
        config_obj.host = sftp_config["host"]
        config_obj.port = sftp_config["port"]
        config_obj.username = sftp_config["username"]
        config_obj.password = sftp_config["password"]
        config_obj.upload_path = sftp_config["remote_path"]
        config_obj.key_path = None
        
        try:
            success = upload_to_slate(csv_path, config_obj)
        except Exception as e:
            import traceback
            traceback.print_exc()
            os.remove(csv_path)
            return JSONResponse(status_code=500, content={"error": f"SFTP upload failed: {str(e)}"})
        
        os.remove(csv_path)
        if not success:
            return JSONResponse(status_code=500, content={"error": "SFTP upload failed."})
        """
        
        # 4. Mark rows as exported
        try:
            # Extract document IDs from rows
            document_ids = [row.get("id") for row in rows if row.get("id")]
            if document_ids:
                # Update the exported_at timestamp for these documents
                timestamp = datetime.now(timezone.utc).isoformat()
                update_payload = {
                    "exported_at": timestamp
                }
                update_response = supabase_client.table("reviewed_data") \
                    .update(update_payload) \
                    .in_("document_id", document_ids) \
                    .execute()
                print(f"✅ Successfully marked {len(document_ids)} records as exported")
        except Exception as e:
            print(f"⚠️ Warning: Failed to mark records as exported: {str(e)}")
            # Don't return error since the upload was successful
            # Just log the warning and continue
        
        return JSONResponse(status_code=200, content={"status": "success", "debug_path": debug_csv_path})
    except Exception as e:
        import traceback
        traceback.print_exc()
        return JSONResponse(status_code=500, content={"error": f"Internal error: {str(e)}"}) 