import os
from dotenv import load_dotenv
from supabase import create_client
from google.cloud import documentai_v1 as documentai
import googlemaps

load_dotenv()

SUPABASE_URL = os.getenv("SUPABASE_URL")
SUPABASE_KEY = os.getenv("SUPABASE_SERVICE_ROLE_KEY")

print("\n=== SUPABASE CLIENT INITIALIZATION ===")
print(f"🔑 SUPABASE_URL: {SUPABASE_URL}")
print(f"🔑 SUPABASE_KEY present: {'Yes' if SUPABASE_KEY else 'No'}")
print(f"🔑 SUPABASE_KEY length: {len(SUPABASE_KEY) if SUPABASE_KEY else 0}")
print(f"🔑 SUPABASE_KEY first 10 chars: {SUPABASE_KEY[:10] if SUPABASE_KEY else 'None'}")

if not SUPABASE_URL or not SUPABASE_KEY:
    raise ValueError("Missing required Supabase environment variables")

try:
    supabase_client = create_client(SUPABASE_URL, SUPABASE_KEY)
    supabase_auth = create_client(SUPABASE_URL, SUPABASE_KEY)
    print("✅ Supabase clients initialized successfully")
    print("✅ Service role key verified")
except Exception as e:
    print(f"❌ Error initializing Supabase clients: {str(e)}")
    raise

print("=== SUPABASE CLIENT INITIALIZATION END ===\n")

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