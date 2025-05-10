import os
from dotenv import load_dotenv
from supabase import create_client
from google.cloud import documentai_v1 as documentai
import googlemaps

load_dotenv()

SUPABASE_URL = os.getenv("SUPABASE_URL")
SUPABASE_KEY = os.getenv("SUPABASE_SERVICE_ROLE_KEY")
supabase_client = create_client(SUPABASE_URL, SUPABASE_KEY)
supabase_auth = create_client(SUPABASE_URL, SUPABASE_KEY)

# Document AI
try:
    docai_client = documentai.DocumentProcessorServiceClient()
    project_id = os.getenv("GOOGLE_PROJECT_ID")
    location = os.getenv("DOCAI_LOCATION")
    processor_id = os.getenv("DOCAI_PROCESSOR_ID")
    docai_name = f"projects/{project_id}/locations/{location}/processors/{processor_id}"
except Exception:
    docai_client = None
    docai_name = None

# Google Maps
try:
    gmaps_client = googlemaps.Client(key=os.getenv("GOOGLE_MAPS_API_KEY"))
except Exception:
    gmaps_client = None

mime_type = "image/png"

print(f"SUPABASE_URL: {SUPABASE_URL}") 