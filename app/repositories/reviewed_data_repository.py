from fastapi import HTTPException
import json
from datetime import datetime, timezone

def upsert_reviewed_data(supabase_client, data):
    print(f"[REVIEWED DATA DEBUG] === UPSERT OPERATION START ===")
    print(f"[REVIEWED DATA DEBUG] Document ID: {data.get('document_id')}")
    print(f"[REVIEWED DATA DEBUG] Review Status: {data.get('review_status')}")
    print(f"[REVIEWED DATA DEBUG] Fields requiring review:")
    for field_name, field_data in data.get('fields', {}).items():
        if isinstance(field_data, dict) and field_data.get('requires_human_review'):
            print(f"  - {field_name}: {field_data.get('review_notes')}")
    
    # Check if record exists
    existing = supabase_client.table("reviewed_data").select("*").eq("document_id", data['document_id']).maybe_single().execute()
    if existing and existing.data:
        print(f"[REVIEWED DATA DEBUG] Existing record found:")
        print(f"  - Current review_status: {existing.data.get('review_status')}")
        print(f"  - Current updated_at: {existing.data.get('updated_at')}")
    
    # Perform upsert
    response = supabase_client.table("reviewed_data").upsert(data, on_conflict="document_id").execute()
    
    # Log the response
    if hasattr(response, 'data') and response.data:
        print(f"[REVIEWED DATA DEBUG] Upsert response:")
        print(f"  - New review_status: {response.data[0].get('review_status')}")
        print(f"  - New updated_at: {response.data[0].get('updated_at')}")
    
    if hasattr(response, 'error') and response.error:
        print(f"[REVIEWED DATA DEBUG] ❌ Upsert error: {response.error}")
        raise HTTPException(status_code=500, detail=f"Supabase error: {response.error}")
    
    print(f"[REVIEWED DATA DEBUG] === UPSERT OPERATION END ===\n")
    return response

def get_reviewed_data_by_document_id(supabase_client, document_id):
    response = supabase_client.table("reviewed_data").select("*").eq("document_id", document_id).maybe_single().execute()
    if not response or not response.data:
        raise HTTPException(status_code=404, detail="Reviewed data not found")
    return response.data
