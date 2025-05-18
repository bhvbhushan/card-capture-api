import sys
from google.cloud import documentai_v1 as documentai
from PIL import Image
import os

# TODO: Set these to your values
PROJECT_ID = "gen-lang-client-0493571343"
LOCATION = "us"  # Format: 'us' or 'eu'
PROCESSOR_ID = "894b9758c2215ed6"  # Create processor in Cloud Console

TRIM_OUTPUT_DIR = "/Users/kregboyd/Applications/card-capture-api/trim_image_test"
TRIM_OUTPUT_PATH = os.path.join(TRIM_OUTPUT_DIR, "cropped_output.png")

# Percentage to expand the bounding box (e.g., 0.5 for 50% larger)
def crop_image(image_path, min_x, min_y, max_x, max_y, output_path=TRIM_OUTPUT_PATH, percent_expand=0.5):
    img = Image.open(image_path)
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
    print(f"Cropped image saved to {output_path}")

def print_entity_bounding_boxes(document, image_path):
    if not hasattr(document, "entities") or not document.entities:
        print("No entities found in document.")
        return

    all_vertices = []

    for entity in document.entities:
        entity_type = entity.type_ if hasattr(entity, 'type_') else getattr(entity, 'type', None)
        mention_text = entity.mention_text if hasattr(entity, 'mention_text') else getattr(entity, 'mention_text', None)
        print(f"Entity: {entity_type} | Value: {mention_text}")

        if entity.page_anchor and entity.page_anchor.page_refs:
            for page_ref in entity.page_anchor.page_refs:
                page_index = page_ref.page
                page = document.pages[page_index]
                width = page.dimension.width
                height = page.dimension.height

                if page_ref.bounding_poly.normalized_vertices:
                    print("  Bounding Box (normalized -> pixel):")
                    for v in page_ref.bounding_poly.normalized_vertices:
                        pixel_x = v.x * width
                        pixel_y = v.y * height
                        print(f"    ({pixel_x:.1f}, {pixel_y:.1f})")
                        all_vertices.append((pixel_x, pixel_y))
                elif page_ref.bounding_poly.vertices:
                    print("  Bounding Box (absolute):")
                    for v in page_ref.bounding_poly.vertices:
                        print(f"    ({v.x}, {v.y})")
                        all_vertices.append((v.x, v.y))

    # Calculate overall bounding box
    if all_vertices:
        xs, ys = zip(*all_vertices)
        min_x, max_x = min(xs), max(xs)
        min_y, max_y = min(ys), max(ys)
        print(f"\nOverall bounding box: Top-Left ({min_x:.1f}, {min_y:.1f}), Bottom-Right ({max_x:.1f}, {max_y:.1f})")
        crop_image(image_path, min_x, min_y, max_x, max_y, percent_expand=0.5)
    else:
        print("No bounding box vertices found for any entity.")

def parse_document(image_path):
    # Instantiates a client
    client = documentai.DocumentProcessorServiceClient()

    # The full resource name of the processor
    name = f"projects/{PROJECT_ID}/locations/{LOCATION}/processors/{PROCESSOR_ID}"

    # Read the file into memory
    with open(image_path, "rb") as image:
        image_content = image.read()

    # Configure the process request
    raw_document = documentai.RawDocument(content=image_content, mime_type="image/jpeg")
    request = documentai.ProcessRequest(
        name=name,
        raw_document=raw_document,
    )

    # Use the client to process the image
    result = client.process_document(request=request)
    document = result.document

    print(f"Document text: {document.text[:100]}...")  # Print first 100 chars

    # Debug: Print the number of form fields and their layouts
    for page_num, page in enumerate(document.pages):
        print(f"Page {page_num+1}:")
        print(f"  Number of form fields: {len(page.form_fields)}")
        for i, form_field in enumerate(page.form_fields):
            print(f"  Field {i+1}:")
            print(f"    Field Name Text Anchor: {getattr(form_field.field_name, 'text_anchor', None)}")
            print(f"    Field Value Text Anchor: {getattr(form_field.field_value, 'text_anchor', None)}")
            if form_field.field_name and form_field.field_name.layout:
                print(f"    Field Name Layout: {form_field.field_name.layout}")
            if form_field.field_value and form_field.field_value.layout:
                print(f"    Field Value Layout: {form_field.field_value.layout}")

    # Original output for bounding boxes
    for page in document.pages:
        for form_field in page.form_fields:
            field_name = form_field.field_name.text_anchor.content if form_field.field_name else ""
            field_value = form_field.field_value.text_anchor.content if form_field.field_value else ""
            print(f"Field: {field_name} | Value: {field_value}")

            # Print bounding box for the field name
            if form_field.field_name and form_field.field_name.layout and form_field.field_name.layout.bounding_poly:
                print("  Field Name Bounding Box:")
                for vertex in form_field.field_name.layout.bounding_poly.vertices:
                    print(f"    ({vertex.x}, {vertex.y})")

            # Print bounding box for the field value
            if form_field.field_value and form_field.field_value.layout and form_field.field_value.layout.bounding_poly:
                print("  Field Value Bounding Box:")
                for vertex in form_field.field_value.layout.bounding_poly.vertices:
                    print(f"    ({vertex.x}, {vertex.y})")

    # New: Print bounding boxes from entities (custom processor) and crop image
    print_entity_bounding_boxes(document, image_path)

if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("Usage: python image_trimmer_test.py /path/to/image.jpg")
        exit(1)
    parse_document(sys.argv[1])