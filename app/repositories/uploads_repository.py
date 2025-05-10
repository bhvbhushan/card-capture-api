from datetime import datetime, timezone
from typing import Dict, Any

def insert_processing_job_db(supabase_client, job_data: Dict[str, Any]):
    return supabase_client.table("processing_jobs").insert(job_data).execute()

def insert_extracted_data_db(supabase_client, insert_data: Dict[str, Any]):
    return supabase_client.table("extracted_data").insert(insert_data).execute()

def insert_upload_notification_db(supabase_client, notification_data: Dict[str, Any]):
    return supabase_client.table("upload_notifications").insert(notification_data).execute()

def select_upload_notification_db(supabase_client, document_id: str):
    return supabase_client.table("upload_notifications") \
        .select("*") \
        .eq("document_id", document_id) \
        .order("timestamp", desc=True) \
        .limit(1) \
        .execute()

def select_extracted_data_image_db(supabase_client, document_id: str):
    return supabase_client.table("extracted_data") \
        .select("image_path, trimmed_image_path") \
        .eq("document_id", document_id) \
        .maybe_single() \
        .execute() 