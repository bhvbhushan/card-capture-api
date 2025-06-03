import os
import json
from datetime import datetime, timezone
from typing import Dict, Any, Tuple
from google.cloud import documentai_v1 as documentai
from PIL import Image
from app.config import PROJECT_ID, DOCAI_LOCATION, TRIMMED_FOLDER
from app.utils.retry_utils import retry_with_exponential_backoff, log_debug

def process_image_with_docai(image_path: str, processor_id: str) -> Tuple[Dict[str, Any], str]:
    """
    Single, reliable DocAI processing function that:
    1. Calls DocAI API
    2. Extracts entities with confidence scores and bounding boxes
    3. Crops image based on detected entities
    4. Returns standardized field format and cropped image path
    
    Args:
        image_path: Path to the input image
        processor_id: DocAI processor ID to use
        
    Returns:
        Tuple of (field_data_dict, cropped_image_path)
    """
    try:
        # Log image details
        log_debug(f"Processing image: {image_path}", service="docai")
        log_debug(f"Image exists: {os.path.exists(image_path)}", service="docai")
        log_debug(f"Image size: {os.path.getsize(image_path)} bytes", service="docai")
        
        # Initialize DocAI client
        client = documentai.DocumentProcessorServiceClient()
        name = f"projects/{PROJECT_ID}/locations/{DOCAI_LOCATION}/processors/{processor_id}"
        
        log_debug(f"Using DocAI processor: {name}", service="docai")
        
        # Read the file into memory
        with open(image_path, "rb") as image:
            content = image.read()
            log_debug(f"Read {len(content)} bytes from image", service="docai")
        
        # Configure the process request
        request = documentai.ProcessRequest(
            name=name,
            raw_document=documentai.RawDocument(
                content=content,
                mime_type="image/png"
            )
        )
        
        log_debug("Sending request to DocAI...", service="docai")
        
        # Process the document with retry logic
        try:
            result = retry_with_exponential_backoff(
                func=lambda: client.process_document(request=request),
                max_retries=3,
                operation_name="DocAI document processing",
                service="docai"
            )
            log_debug("DocAI processing successful", service="docai")
        except Exception as e:
            log_debug(f"DocAI error details: {str(e)}", service="docai")
            log_debug(f"Error type: {type(e)}", service="docai")
            if hasattr(e, 'response'):
                log_debug(f"Response: {e.response}", service="docai")
            raise
        
        document = result.document
        
        log_debug("DocAI response received", {
            "text_length": len(document.text),
            "num_pages": len(document.pages),
            "num_entities": len(document.entities)
        }, service="docai")
        
        # Extract field data and bounding boxes
        field_data = {}
        all_vertices = []
        
        log_debug("=== EXTRACTING ENTITIES ===", service="docai")
        for entity in document.entities:
            field_name = entity.type_.lower().replace(" ", "_")
            field_value = entity.mention_text.strip() if entity.mention_text else ""
            confidence = float(entity.confidence) if entity.confidence else 0.0
            
            log_debug(f"Entity: {field_name}", {
                "value": field_value,
                "confidence": confidence
            }, service="docai")
            
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
                                bounding_box.append([pixel_x, pixel_y])
                                all_vertices.append((pixel_x, pixel_y))
                        elif page_ref.bounding_poly.vertices:
                            for vertex in page_ref.bounding_poly.vertices:
                                bounding_box.append([vertex.x, vertex.y])
                                all_vertices.append((vertex.x, vertex.y))
            
            # Create standardized field data structure
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
        
        log_debug("Extracted fields", list(field_data.keys()), service="docai")
        
        # Crop image based on detected entities
        cropped_image_path = _crop_image_from_entities(image_path, all_vertices)
        
        log_debug("=== DOCAI PROCESSING COMPLETE ===", service="docai")
        log_debug(f"Cropped image saved to: {cropped_image_path}", service="docai")
        
        return field_data, cropped_image_path
        
    except Exception as e:
        log_debug(f"ERROR in DocAI processing: {str(e)}", service="docai")
        raise Exception(f"DocAI processing failed: {str(e)}")

def _crop_image_from_entities(input_path: str, all_vertices: list, percent_expand: float = 0.5) -> str:
    """
    Crop image based on bounding box vertices from detected entities
    
    Args:
        input_path: Path to input image
        all_vertices: List of (x, y) coordinates from all entities
        percent_expand: Percentage to expand the bounding box
        
    Returns:
        Path to cropped image
    """
    try:
        if not all_vertices:
            log_debug("No vertices found, returning original image", service="docai")
            return input_path
        
        # Calculate bounding box
        xs, ys = zip(*all_vertices)
        min_x, max_x = min(xs), max(xs)
        min_y, max_y = min(ys), max(ys)
        
        log_debug("Bounding box coordinates", {
            "min_x": min_x, "max_x": max_x,
            "min_y": min_y, "max_y": max_y
        }, service="docai")
        
        # Open image and calculate crop area with expansion
        img = Image.open(input_path)
        box_width = max_x - min_x
        box_height = max_y - min_y
        expand_x = box_width * (percent_expand / 2)
        expand_y = box_height * (percent_expand / 2)
        
        left = max(int(min_x - expand_x), 0)
        top = max(int(min_y - expand_y), 0)
        right = min(int(max_x + expand_x), img.width)
        bottom = min(int(max_y + expand_y), img.height)
        
        log_debug("Crop coordinates", {
            "left": left, "top": top, "right": right, "bottom": bottom
        }, service="docai")
        
        # Crop and save image
        cropped_img = img.crop((left, top, right, bottom))
        filename = os.path.basename(input_path)
        name, ext = os.path.splitext(filename)
        output_path = os.path.join(TRIMMED_FOLDER, f"{name}_trimmed{ext}")
        
        os.makedirs(os.path.dirname(output_path), exist_ok=True)
        cropped_img.save(output_path)
        
        log_debug(f"Image cropped and saved to: {output_path}", service="docai")
        return output_path
        
    except Exception as e:
        log_debug(f"ERROR in image cropping: {str(e)}", service="docai")
        return input_path  # Return original if cropping fails 