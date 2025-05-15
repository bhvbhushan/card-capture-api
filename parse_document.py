from datetime import datetime
from google.cloud import documentai_v1 as documentai
from google.cloud import vision
import google.generativeai as genai
import os
import io
import re
import json
import string
from dotenv import load_dotenv
import uuid
from supabase import create_client
import googlemaps
import base64

from app.config import GEMINI_MODEL

# === 🔧 CONFIG ===
os.environ["GOOGLE_APPLICATION_CREDENTIALS"] = "service_account.json"
project_id = "gen-lang-client-0493571343"
location = "us"
processor_id = "894b9758c2215ed6"
file_path = "/Users/kregboyd/Desktop/card-capture/page_17.png"
mime_type = "image/png"

# Load .env values
load_dotenv(dotenv_path="variables.env")
SUPABASE_DB_URL = os.getenv("SUPABASE_DB_URL") or os.getenv("LOCAL_SUPABASE_DB_URL")
SUPABASE_KEY = os.getenv("SUPABASE_SERVICE_ROLE_KEY") or os.getenv("LOCAL_SUPABASE_SERVICE_ROLE_KEY")
GOOGLE_MAPS_API_KEY = os.getenv("GOOGLE_CLOUD_API_KEY")
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY")

supabase_client = create_client(SUPABASE_DB_URL, SUPABASE_KEY)
gmaps = googlemaps.Client(key=GOOGLE_MAPS_API_KEY)
genai.configure(api_key=GEMINI_API_KEY)

def get_text_from_anchor(anchor, full_text):
    if anchor.text_segments:
        parts = []
        for segment in anchor.text_segments:
            start = int(segment.start_index or 0)
            end = int(segment.end_index)
            parts.append(full_text[start:end])
        return "".join(parts).strip()
    return ""

def get_gemini_corrections_with_image(low_conf_fields, full_context_fields, image_path):
    prompt_text = f"""
    Review the field values from a student information card (OCR parsed data). Your job is to fix low-confidence fields using both the data and the image. Act like a human who's job is to review the card and input it into a CRM accurately. If you're not confident in your correction do not update the field and mark it low confidence.
    Return every low-confidence field with your own gemini_confidence score.

    OCR Low-confidence Fields:
    {json.dumps(low_conf_fields, indent=2)}

    Full Context:
    {json.dumps(full_context_fields, indent=2)}

    Return JSON like:
    {{
      "field_name": {{
        "value": "Corrected or Verified Value",
        "gemini_confidence": 0.94
      }}
    }}
    """
    model = genai.GenerativeModel(GEMINI_MODEL)

    try:
        with open(image_path, "rb") as img_file:
            image_bytes = img_file.read()
        response = model.generate_content([
            prompt_text,
            {"mime_type": "image/jpeg", "data": image_bytes}
        ])
        print("Gemini raw response:\n", response.text)
        raw = re.sub(r"```json|```", "", response.text).strip()
        cleaned = re.sub(r",(\s*[\]}])", r"\1", raw)
        return json.loads(cleaned)
    except Exception as e:
        print(f"❌ Gemini error: {e}")
        return {}

def validate_address(address, gmaps):
    try:
        geocode_result = gmaps.geocode(address)
        if geocode_result:
            return geocode_result[0]["formatted_address"], True
        else:
            return None, False
    except Exception as e:
        print(f"Geocoding error: {e}")
        return None, False

def process_document(image_base64=None):
    docai_client = documentai.DocumentProcessorServiceClient()
    name = f"projects/{project_id}/locations/{location}/processors/{processor_id}"

    if image_base64 is not None:
        image_content = base64.b64decode(image_base64)
    else:
        with open(file_path, "rb") as image:
            image_content = image.read()

    raw_document = documentai.RawDocument(content=image_content, mime_type=mime_type)
    request = documentai.ProcessRequest(name=name, raw_document=raw_document)
    result = docai_client.process_document(request=request)
    document = result.document
    full_text = document.text

    document_id = str(uuid.uuid4())
    image_id = str(uuid.uuid4())
    image_save_path = os.path.join("/tmp", f"{image_id}.jpg")
    try:
        with open(image_save_path, "wb") as f:
            f.write(image_content)
    except Exception as e:
        print(f"Failed to save image to disk: {e}")
        image_save_path = None

    # ⬇️ Extract fields using page.form_fields + resolved anchors
    extracted_fields = {}
    for page in document.pages:
        for field in page.form_fields:
            key = get_text_from_anchor(field.field_name.text_anchor, full_text)
            value = get_text_from_anchor(field.field_value.text_anchor, full_text)
            confidence = round(field.field_value.confidence, 4)
            if key:
                extracted_fields[key] = {
                    "value": value,
                    "vision_confidence": confidence
                }

    print("🧾 Extracted Fields:")
    print(json.dumps(extracted_fields, indent=2))

    print("📝 Inserting into extracted_data...")
    supabase_client.table("extracted_data").insert({
        "document_id": document_id,
        "fields": extracted_fields,
        "image_path": image_save_path
    }).execute()

    print("🧠 Asking Gemini to review low-confidence fields...")
    low_conf_fields = {
        field: data["value"]
        for field, data in extracted_fields.items()
        if data["vision_confidence"] < 0.85
    }
    full_context_fields = {k: v["value"] for k, v in extracted_fields.items()}
    gemini_updates = get_gemini_corrections_with_image(low_conf_fields, full_context_fields, image_save_path)

    reviewed_fields = {}
    required_fields = ["address", "cell", "city_state", "zip_code", "name", "preferred_name"]

    for field, data in extracted_fields.items():
        value = data["value"]
        confidence = data["vision_confidence"]
        source = "vision"
        flags = {}
        review_status = "reviewed"

        if field in gemini_updates:
            value = gemini_updates[field]["value"]
            confidence = gemini_updates[field].get("gemini_confidence", confidence)
            source = "gemini"

        if field in required_fields:
            if not value:
                flags["missing"] = True
                review_status = "human_review"
            if confidence < 0.7:
                flags["low_confidence"] = True
                review_status = "human_review"
            if field == "address":
                _, is_valid = validate_address(value, gmaps)
                if not is_valid:
                    flags["invalid_address"] = True
                    review_status = "human_review"

        reviewed_fields[field] = {
            "value": value,
            "confidence": confidence,
            "source": source,
            "validation_flags": flags,
            "requires_human_review": review_status == "human_review",
            "reviewed": review_status == "reviewed"
        }

    print("✅ Reviewed Fields:")
    print(json.dumps(reviewed_fields, indent=2))

    print("📦 Inserting into reviewed_data...")
    supabase_client.table("reviewed_data").insert({
        "document_id": document_id,
        "fields": reviewed_fields,
        "review_status": "reviewed"
    }).execute()

    print(f"✅ Processing complete for document: {document_id}")

if __name__ == "__main__":
    if os.getenv("SUPABASE_ENV") == "supabase":
        print("Running in Supabase Function")
        import sys
        image_base64 = sys.argv[1]
        process_document(image_base64)
    else:
        print("Running Locally")
        process_document()
