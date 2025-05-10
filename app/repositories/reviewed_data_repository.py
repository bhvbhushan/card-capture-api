from fastapi import HTTPException

def upsert_reviewed_data(supabase_client, data):
    response = supabase_client.table("reviewed_data").upsert(data, on_conflict="document_id").execute()
    if hasattr(response, 'error') and response.error:
        raise HTTPException(status_code=500, detail=f"Supabase error: {response.error}")
    return response

def get_reviewed_data_by_document_id(supabase_client, document_id):
    response = supabase_client.table("reviewed_data").select("*").eq("document_id", document_id).maybe_single().execute()
    if not response or not response.data:
        raise HTTPException(status_code=404, detail="Reviewed data not found")
    return response.data
