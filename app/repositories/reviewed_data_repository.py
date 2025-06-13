from fastapi import HTTPException
import json
from datetime import datetime, timezone

def upsert_reviewed_data(supabase_client, data):
    """
    Upsert reviewed data to the database
    """
    print(f"[REVIEWED DATA DEBUG] === UPSERT OPERATION START ===")
    
    # Track critical fields being saved
    critical_fields = ["cell", "date_of_birth"]
    print(f"[REVIEWED DATA DEBUG] 🔍 CRITICAL FIELDS BEING SAVED:")
    for field in critical_fields:
        field_data = data.get("fields", {}).get(field, {})
        print(f"[REVIEWED DATA DEBUG] {field}:")
        print(f"  - value: {field_data.get('value')}")
        print(f"  - original_value: {field_data.get('original_value')}")
        print(f"  - source: {field_data.get('source')}")
        print(f"  - enabled: {field_data.get('enabled')}")
        print(f"  - required: {field_data.get('required')}")
    
    try:
        result = supabase_client.table("reviewed_data").upsert(data, on_conflict="document_id").execute()
        print(f"[REVIEWED DATA DEBUG] === UPSERT OPERATION COMPLETE ===")
        return result
    except Exception as e:
        print(f"[REVIEWED DATA DEBUG] Error during upsert: {str(e)}")
        raise

def get_reviewed_data_by_document_id(supabase_client, document_id):
    response = supabase_client.table("reviewed_data").select("*").eq("document_id", document_id).maybe_single().execute()
    if not response or not response.data:
        raise HTTPException(status_code=404, detail="Reviewed data not found")
    return response.data
