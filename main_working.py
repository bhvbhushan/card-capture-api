from fastapi import FastAPI, File, UploadFile
from fastapi.responses import JSONResponse
from fastapi.middleware.cors import CORSMiddleware
from fastapi import BackgroundTasks
import shutil
import os
import json
import uuid
from datetime import datetime, timezone
from supabase import create_client
from dotenv import load_dotenv
import googlemaps
from google.cloud import documentai_v1 as documentai
from google.cloud import vision
import google.generativeai as genai
import io
import re
import string

# === CONFIG ===
os.environ["GOOGLE_APPLICATION_CREDENTIALS"] = "service_account.json"
project_id = "gen-lang-client-0493571343"
location = "us"
processor_id = "894b9758c2215ed6"
mime_type = "image/png"

# === SUPABASE CONFIG ===
load_dotenv(dotenv_path="variables.env")
SUPABASE_URL = os.getenv("SUPABASE_DB_URL")
SUPABASE_KEY = os.getenv("SUPABASE_SERVICE_ROLE_KEY")
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY")
GOOGLE_MAPS_API_KEY = os.getenv("GOOGLE_MAPS_API_KEY")

supabase_client = create_client(SUPABASE_URL, SUPABASE_KEY)
genai.configure(api_key=GEMINI_API_KEY)

app = FastAPI()

# CORS setup
app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:8080"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

UPLOAD_FOLDER = "/tmp"
os.makedirs(UPLOAD_FOLDER, exist_ok=True)

# === HELPERS ===
def normalize_word(word):
    return word.lower().translate(str.maketrans('', '', string.punctuation))

def get_ocr_confidence_map(image_path):
    client = vision.ImageAnnotatorClient()
    with io.open(image_path, "rb") as image_file:
        content = image_file.read()
    image = vision.Image(content=content)
    response = client.document_text_detection(image=image)

    flat_conf = {}
    for page in response.full_text_annotation.pages:
        for block in page.blocks:
            for paragraph in block.paragraphs:
                for word in paragraph.words:
                    word_text = ''.join([s.text for s in word.symbols])
                    norm = normalize_word(word_text)
                    flat_conf[norm] = word.confidence
    return flat_conf

def estimate_confidence_from_ocr(value, ocr_conf_map):
    tokens = re.findall(r"\w+", str(value).lower())
    scores = []

    for token in tokens:
        if token in ocr_conf_map:
            scores.append(ocr_conf_map[token])
        else:
            for ocr_token, conf in ocr_conf_map.items():
                if token in ocr_token or ocr_token in token:
                    scores.append(conf)
                    break

    return round(sum(scores) / len(scores), 4) if scores else 0.0

def get_gemini_review(all_fields, image_path):
    prompt = f"""
You are reviewing OCR-parsed student contact card data. Your task is to validate and correct the fields based on the image.

- For each field, check if the value is correct. If unsure or if the word appears incorrect, mark it with a confidence below 0.85 for human review.
- Correct the value if confident, and return the updated value with a confidence score.

Full field context:
{json.dumps(all_fields, indent=2)}
"""
    model = genai.GenerativeModel("gemini-1.5-pro-latest")

    try:
        with open(image_path, "rb") as f:
            image_bytes = f.read()
        response = model.generate_content([
            prompt,
            {"mime_type": "image/jpeg", "data": image_bytes}
        ])
        
        raw = re.sub(r"```json|```", "", response.text).strip()
        cleaned = re.sub(r",(\s*[\]}])", r"\1", raw)

        # Debugging print: raw response and cleaned output
        print(f"Raw response from Gemini: {response.text}")
        print(f"Cleaned response: {cleaned}")
        
        # Ensure the response is a valid dictionary
        gemini_dict = json.loads(cleaned)
        if isinstance(gemini_dict, dict):
            return gemini_dict
        else:
            print("❌ Error: Gemini response is not a valid dictionary.")
            return {}

    except Exception as e:
        print(f"❌ Error in Gemini review: {e}")
        return {}  # Return an empty dict if there's an error

# Google Maps API to validate address
def validate_address_with_google(address, zip_code):
    gmaps = googlemaps.Client(key=GOOGLE_MAPS_API_KEY)

    try:
        # Construct address for validation
        full_address = f"{address}, {zip_code}"
        geocode_result = gmaps.geocode(full_address)

        if geocode_result:
            # Return the formatted address if valid
            return geocode_result[0]["formatted_address"]
        else:
            print(f"❌ Address not found for: {full_address}")
            return None
    except Exception as e:
        print(f"❌ Error validating address: {e}")
        return None

# === MAIN PIPELINE ===

def process_image(image_path):
    print(f"🔍 Processing image at {image_path} with Document AI...")

    # Perform OCR with Google Document AI
    docai_client = documentai.DocumentProcessorServiceClient()
    docai_name = f"projects/{project_id}/locations/{location}/processors/{processor_id}"

    with open(image_path, "rb") as image:
        image_content = image.read()

    raw_document = documentai.RawDocument(content=image_content, mime_type=mime_type)
    request = documentai.ProcessRequest(name=docai_name, raw_document=raw_document)
    result = docai_client.process_document(request=request)
    document = result.document

    print(f"✅ OCR processing completed for {image_path}")

    ocr_conf_map = get_ocr_confidence_map(image_path)

    extracted_fields = {}
    for entity in document.entities:
        key = entity.type_
        value = entity.mention_text
        confidence = estimate_confidence_from_ocr(value, ocr_conf_map)
        extracted_fields[key] = {
            "value": value,
            "vision_confidence": confidence
        }

    # Return extracted fields for further processing
    return {"document_id": str(uuid.uuid4()), "extracted_fields": extracted_fields}

# === MAIN PIPELINE ===
@app.post("/upload")
async def upload_file(background_tasks: BackgroundTasks, file: UploadFile = File(...)):
    print("📤 Upload received. Starting image processing...")

    temp_path = os.path.join(UPLOAD_FOLDER, f"{uuid.uuid4()}_{file.filename}")

    # Save uploaded file
    with open(temp_path, "wb") as buffer:
        shutil.copyfileobj(file.file, buffer)

    try:
        # Run Document AI + Vision pipeline (OCR)
        document_id = uuid.uuid4()  # Generate a unique UUID for the document_id
        extracted_fields = process_image(temp_path)  # Assume this returns the extracted fields

        print(f"✅ Extracted fields: {extracted_fields}")

        # Save to extracted_data table
        response = supabase_client.table("extracted_data").insert({
            "document_id": str(document_id),  # Ensure it's stored as a string UUID
            "fields": extracted_fields,  # Store the extracted fields as they are
            "image_path": temp_path
        }).execute()

        print(f"✅ Saved extracted data for document_id: {document_id} into extracted_data.")
        print(f"Response: {response}")

        # Respond with the status to update the progress bar and show success toast
        response_data = {
            "status": "extracted_data_saved",
            "message": "OCR extraction complete, starting Gemini review."
        }

        # Add the background task to run Gemini review **after** the response is sent
        background_tasks.add_task(run_gemini_review, str(document_id), extracted_fields, temp_path)

        # Return status to the front-end
        return JSONResponse(content=response_data)

    except Exception as e:
        print(f"❌ Error processing image: {e}")
        return JSONResponse(status_code=500, content={"error": "Failed to process image."})

# Function to handle the Gemini review process (no background_tasks.add_task here)
async def run_gemini_review(document_id: str, extracted_fields: dict, image_path: str):
    print(f"🧠 Gemini review started for document_id: {document_id}")

    # Run Gemini review
    gemini_updates = get_gemini_review(extracted_fields, image_path)

    print(f"🧠 Gemini review completed for document_id: {document_id}")
    print(f"✅ Gemini updates: {gemini_updates}")

    # Update the reviewed data
    reviewed_fields = {}

    # Extract the extracted_fields from gemini response.
    gemini_extracted_fields = gemini_updates.get("extracted_fields", {})
    original_extracted_fields = extracted_fields.get("extracted_fields", {}) # Access the inner extracted_fields

    for field, data in original_extracted_fields.items(): #iterate through the inner extracted fields
        print(f"✅ Field: {field}, Data: {data}")

        if isinstance(data, dict):
            value = data.get("value", None)
            confidence = data.get("vision_confidence", 0.5)
        else:
            print(f"❌ Error: Expected dictionary for field {field}, but got {type(data)}. Skipping...")
            value = None
            confidence = 0.5

        source = "vision"

        # Apply Gemini updates if available
        if field in gemini_extracted_fields:
            if isinstance(gemini_extracted_fields[field], dict):
                new_value = gemini_extracted_fields[field].get("value")
                new_confidence = gemini_extracted_fields[field].get("vision_confidence", confidence)
            else:
                print(f"Unexpected type for gemini_extracted_fields[{field}]: {type(gemini_extracted_fields[field])}")
                new_value = gemini_extracted_fields[field]
                new_confidence = confidence

            if new_confidence >= 0.85:
                confidence = new_confidence
                value = new_value
                source = "gemini"
            else:
                confidence = 0.5
                value = new_value
                source = "gemini"

        reviewed_fields[field] = {
            "value": value,
            "confidence": confidence,
            "source": source,
        }

    # Save to reviewed_data table
    response = supabase_client.table("reviewed_data").insert({
        "document_id": document_id,  # Use the string UUID as intended
        "fields": reviewed_fields,
        "review_status": "reviewed"
    }).execute()

    print(f"✅ Saved reviewed data for document_id: {document_id} into reviewed_data.")
    print(f"Response: {response}")

@app.post("/review")
async def review_document(data: dict):
    try:
        document_id = data.get("document_id")
        if not document_id:
            print("❌ No document_id provided.")
            return JSONResponse(status_code=400, content={"error": "No document_id provided"})

        # Fetch extracted fields from Supabase
        response = supabase_client.table("extracted_data").select("*").eq("document_id", document_id).execute()
        if not response.data:
            print(f"❌ No data found for document_id: {document_id}")
            return JSONResponse(status_code=400, content={"error": "Document not found."})

        extracted_fields = response.data[0]["fields"]
        print(f"✅ Found extracted fields: {extracted_fields}")

        # Start Gemini review
        gemini_updates = get_gemini_review(extracted_fields, "path_to_image")
        return JSONResponse(content={"message": "Gemini review completed."})

    except Exception as e:
        print(f"❌ Error processing image: {e}")
        return JSONResponse(status_code=500, content={"error": "Failed to process image."})

@app.get("/health")
def health_check():
    return {"status": "ok"}