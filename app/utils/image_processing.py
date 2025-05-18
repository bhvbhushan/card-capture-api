import os
from PIL import Image
from google.cloud import documentai_v1 as documentai
from app.config import PROJECT_ID, DOCAI_LOCATION, DOCAI_PROCESSOR_ID, TRIMMED_FOLDER

def trim_image_with_docai(input_path: str, output_path: str = None, percent_expand: float = 0.5) -> str:
    """
    Uses Google Document AI to find the bounding box of form fields, crops the image with a percentage expansion,
    and saves it to output_path. Returns the output path, or input_path if anything fails.
    """
    try:
        # Set up output path
        if not output_path:
            filename = os.path.basename(input_path)
            name, ext = os.path.splitext(filename)
            output_path = os.path.join(TRIMMED_FOLDER, f"{name}_trimmed{ext}")
        # Set up Document AI client
        client = documentai.DocumentProcessorServiceClient()
        name = f"projects/{PROJECT_ID}/locations/{DOCAI_LOCATION}/processors/{DOCAI_PROCESSOR_ID}"
        with open(input_path, "rb") as image_file:
            image_content = image_file.read()
        raw_document = documentai.RawDocument(content=image_content, mime_type="image/jpeg")
        request = documentai.ProcessRequest(name=name, raw_document=raw_document)
        result = client.process_document(request=request)
        document = result.document
        # Gather all bounding box vertices from entities
        all_vertices = []
        for entity in getattr(document, "entities", []):
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
                            all_vertices.append((pixel_x, pixel_y))
                    elif page_ref.bounding_poly.vertices:
                        for v in page_ref.bounding_poly.vertices:
                            all_vertices.append((v.x, v.y))
        if not all_vertices:
            print("No bounding box vertices found for any entity. Returning original image.")
            return input_path
        xs, ys = zip(*all_vertices)
        min_x, max_x = min(xs), max(xs)
        min_y, max_y = min(ys), max(ys)
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
        cropped_img = img.crop((left, top, right, bottom))
        os.makedirs(os.path.dirname(output_path), exist_ok=True)
        cropped_img.save(output_path)
        print(f"[DocAI] Cropped image saved to {output_path}")
        return output_path
    except Exception as e:
        print(f"[DocAI] Error in trim_image_with_docai: {e}")
        return input_path

def ensure_trimmed_image(original_image_path: str) -> str:
    print(f"🔄 Processing image: {original_image_path}")
    try:
        trimmed_path = trim_image_with_docai(original_image_path)
        if not os.path.exists(trimmed_path):
            print(f"⚠️ Trimmed image not found at: {trimmed_path}")
            return original_image_path
        print(f"✅ Image processed and saved at: {trimmed_path}")
        return trimmed_path
    except Exception as e:
        print(f"❌ Error processing image: {e}")
        return original_image_path 