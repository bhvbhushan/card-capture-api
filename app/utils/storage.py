import os
import mimetypes
import uuid
from datetime import datetime

def upload_to_supabase_storage_from_path(supabase_client, trimmed_path: str, user_id: str, original_filename: str) -> str:
    file_extension = os.path.splitext(original_filename)[1] if original_filename else '.png'
    unique_filename = f"{uuid.uuid4()}{file_extension}"
    today = datetime.now().strftime('%Y-%m-%d')
    storage_path = f"cards-uploads/{user_id}/{today}/{unique_filename}"
    content_type, _ = mimetypes.guess_type(original_filename)
    if not content_type:
        content_type = 'application/octet-stream'
    with open(trimmed_path, "rb") as f:
        trimmed_bytes = f.read()
    res = supabase_client.storage.from_('cards-uploads').upload(
        storage_path.replace('cards-uploads/', ''),
        trimmed_bytes,
        {"content-type": content_type}
    )
    if hasattr(res, 'error') and res.error:
        raise Exception(f"Supabase Storage upload error: {res.error}")
    return storage_path
