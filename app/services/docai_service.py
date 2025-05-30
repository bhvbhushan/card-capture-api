import os
import json
from datetime import datetime, timezone
from typing import Dict, Any, Tuple
from google.cloud import documentai_v1 as documentai
from PIL import Image
from app.config import PROJECT_ID, DOCAI_LOCATION, TRIMMED_FOLDER
from app.services.image_processing_service import ImageProcessingService, TrimConfig
from app.services.settings_service import get_canonical_field_list

def log_docai_debug(message: str, data: Any = None):
    """Write debug message and optional data to docai_debug.log"""
    timestamp = datetime.now(timezone.utc).isoformat()
    with open('docai_debug.log', 'a') as f:
        f.write(f"\n[{timestamp}] {message}\n")
        if data:
            if isinstance(data, (dict, list)):
                f.write(json.dumps(data, indent=2))
            else:
                f.write(str(data))
            f.write("\n")

def process_image_with_docai(image_path: str, processor_id: str) -> Tuple[Dict[str, Any], str]:
    """
    Single, reliable DocAI processing function that:
    1. Calls DocAI API
    2. Extracts entities with confidence scores and bounding boxes
    3. Crops image based on detected entities (using all fields)
    4. Returns standardized field format and cropped image path
    
    Args:
        image_path: Path to the input image
        processor_id: DocAI processor ID to use
        
    Returns:
        Tuple of (field_data_dict, cropped_image_path)
    """
    log_docai_debug("=== DOCAI PROCESSING START ===")
    log_docai_debug(f"Processing image: {image_path}")
    log_docai_debug(f"Using processor: {processor_id}")
    
    try:
        # Set up Document AI client
        client = documentai.DocumentProcessorServiceClient()
        name = f"projects/{PROJECT_ID}/locations/{DOCAI_LOCATION}/processors/{processor_id}"
        
        # Read and process image
        with open(image_path, "rb") as image_file:
            image_content = image_file.read()
        
        raw_document = documentai.RawDocument(content=image_content, mime_type="image/jpeg")
        request = documentai.ProcessRequest(name=name, raw_document=raw_document)
        
        log_docai_debug("Sending request to DocAI...")
        result = client.process_document(request=request)
        document = result.document
        
        log_docai_debug("DocAI response received", {
            "text_length": len(document.text),
            "num_pages": len(document.pages),
            "num_entities": len(document.entities)
        })
        
        # Extract field data and bounding boxes
        field_data = {}
        log_docai_debug("=== EXTRACTING ENTITIES ===")
        for entity in document.entities:
            field_name = entity.type_.lower().replace(" ", "_")
            field_value = entity.mention_text.strip() if entity.mention_text else ""
            confidence = float(entity.confidence) if entity.confidence else 0.0
            
            log_docai_debug(f"Entity: {field_name}", {
                "value": field_value,
                "confidence": confidence
            })
            
            # Extract bounding box coordinates
            bounding_box = []
            if entity.page_anchor and entity.page_anchor.page_refs:
                for page_ref in entity.page_anchor.page_refs:
                    page_index = page_ref.page
                    if page_index < len(document.pages):
                        page = document.pages[page_index]
                        width = page.dimension.width
                        height = page.dimension.height
                        
                        if page_ref.bounding_poly.normalized_vertices:
                            for vertex in page_ref.bounding_poly.normalized_vertices:
                                pixel_x = vertex.x * width
                                pixel_y = vertex.y * height
                                bounding_box.append((pixel_x, pixel_y))
                        elif page_ref.bounding_poly.vertices:
                            for vertex in page_ref.bounding_poly.vertices:
                                bounding_box.append((vertex.x, vertex.y))
            
            if bounding_box:
                field_data[field_name] = {
                    "value": field_value,
                    "confidence": confidence,
                    "bounding_box": bounding_box,
                    "source": "docai",
                    "enabled": True,  # Will be updated by settings service
                    "required": False,  # Will be updated by settings service
                    "requires_human_review": False,  # Will be determined later
                    "review_notes": "",
                    "review_confidence": 0.0  # Will be set by Gemini
                }
        
        log_docai_debug("Extracted fields", list(field_data.keys()))
        
        # Select first and last field from canonical list that are present in field_data
        canonical_fields = get_canonical_field_list()
        present_fields = [f for f in canonical_fields if f in field_data and field_data[f].get('bounding_box')]
        if not present_fields:
            raise Exception("No canonical fields with bounding boxes found for cropping.")
        first_field = present_fields[0]
        last_field = present_fields[-1]
        
        # Use new cropping method
        image_service = ImageProcessingService(TrimConfig(percent_expand=0.5))
        cropped_image_path, trim_metadata = image_service.crop_using_all_fields(
            image_path, field_data, first_field, last_field
        )
        
        log_docai_debug("=== DOCAI PROCESSING COMPLETE ===")
        log_docai_debug(f"Cropped image saved to: {cropped_image_path}")
        log_docai_debug("Trim metadata", trim_metadata)
        
        return field_data, cropped_image_path
        
    except Exception as e:
        log_docai_debug(f"ERROR in DocAI processing: {str(e)}")
        raise Exception(f"DocAI processing failed: {str(e)}") 