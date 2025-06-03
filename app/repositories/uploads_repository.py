from datetime import datetime, timezone
from typing import Dict, Any
from fastapi import HTTPException
from app.utils.db_utils import (
    db_transaction,
    ensure_atomic_updates,
    safe_db_operation,
    validate_db_response,
    handle_db_error
)

@safe_db_operation("Insert processing job")
def insert_processing_job_db(supabase_client, job_data: Dict[str, Any]):
    """Insert a new processing job with proper error handling."""
    return supabase_client.table("processing_jobs").insert(job_data).execute()

@safe_db_operation("Insert extracted data")
def insert_extracted_data_db(supabase_client, data: Dict[str, Any]):
    """Insert extracted data with proper error handling."""
    return supabase_client.table("extracted_data").insert(data).execute()

@safe_db_operation("Get extracted data image")
def select_extracted_data_image_db(supabase_client, document_id: str):
    """Get extracted data image path with proper error handling."""
    return supabase_client.table("extracted_data").select("image_path, trimmed_image_path").eq("document_id", document_id).single().execute()

@ensure_atomic_updates(["processing_jobs", "extracted_data"])
def create_processing_job_with_data(supabase_client, job_data: Dict[str, Any], extracted_data: Dict[str, Any]):
    """
    Atomically create a processing job and its associated extracted data.
    If either operation fails, both are rolled back.
    """
    # Insert processing job
    job_response = supabase_client.table("processing_jobs").insert(job_data).execute()
    if not validate_db_response(job_response, "Insert processing job"):
        raise HTTPException(status_code=500, detail="Failed to create processing job")
        
    # Insert extracted data
    data_response = supabase_client.table("extracted_data").insert(extracted_data).execute()
    if not validate_db_response(data_response, "Insert extracted data"):
        raise HTTPException(status_code=500, detail="Failed to create extracted data")
        
    return {
        "job": job_response.data[0] if job_response.data else None,
        "data": data_response.data[0] if data_response.data else None
    }

@ensure_atomic_updates(["processing_jobs", "reviewed_data"])
def update_job_status_with_review(
    supabase_client,
    job_id: str,
    status: str,
    review_data: Dict[str, Any]
):
    """
    Atomically update a job's status and create/update its review data.
    If either operation fails, both are rolled back.
    """
    # Update job status
    job_response = supabase_client.table("processing_jobs").update({
        "status": status,
        "updated_at": review_data.get("updated_at")
    }).eq("id", job_id).execute()
    
    if not validate_db_response(job_response, "Update job status"):
        raise HTTPException(status_code=500, detail="Failed to update job status")
    
    # Upsert review data
    review_response = supabase_client.table("reviewed_data").upsert(review_data).execute()
    if not validate_db_response(review_response, "Upsert review data"):
        raise HTTPException(status_code=500, detail="Failed to update review data")
    
    return {
        "job": job_response.data[0] if job_response.data else None,
        "review": review_response.data[0] if review_response.data else None
    }

@safe_db_operation("Update processing job")
def update_processing_job_db(supabase_client, job_id: str, updates: Dict[str, Any]):
    """
    Update a processing job - simplified to only use existing tables.
    """
    return supabase_client.table("processing_jobs").update(updates).eq("id", job_id).execute() 