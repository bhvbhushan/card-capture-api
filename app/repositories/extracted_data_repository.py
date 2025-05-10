from fastapi import HTTPException

def upsert_extracted_data(supabase_client, data):
    response = supabase_client.table("extracted_data").upsert(data, on_conflict="document_id").execute()
    if hasattr(response, 'error') and response.error:
        raise HTTPException(status_code=500, detail=f"Supabase error: {response.error}")
    return response

def get_extracted_data_by_document_id(supabase_client, document_id):
    response = supabase_client.table("extracted_data").select("*").eq("document_id", document_id).maybe_single().execute()
    if not response or not response.data:
        raise HTTPException(status_code=404, detail="Extracted data not found")
    return response.data 