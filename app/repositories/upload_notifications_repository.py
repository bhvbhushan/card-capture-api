from fastapi import HTTPException

def insert_upload_notification(supabase_client, notification_data):
    response = supabase_client.table("upload_notifications").insert(notification_data).execute()
    if hasattr(response, 'error') and response.error:
        raise HTTPException(status_code=500, detail=f"Supabase error: {response.error}")
    return response

def get_latest_upload_notification(supabase_client, document_id):
    response = supabase_client.table("upload_notifications") \
        .select("*") \
        .eq("document_id", document_id) \
        .order("timestamp", desc=True) \
        .limit(1) \
        .execute()
    if not response.data:
        return None
    return response.data[0] 