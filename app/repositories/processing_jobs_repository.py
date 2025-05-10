from fastapi import HTTPException

def insert_processing_job(supabase_client, job_data):
    response = supabase_client.table("processing_jobs").insert(job_data).execute()
    if hasattr(response, 'error') and response.error:
        raise HTTPException(status_code=500, detail=f"Supabase error: {response.error}")
    return response

def update_processing_job(supabase_client, job_id, update_data):
    response = supabase_client.table("processing_jobs").update(update_data).eq("id", job_id).execute()
    if hasattr(response, 'error') and response.error:
        raise HTTPException(status_code=500, detail=f"Supabase error: {response.error}")
    return response 