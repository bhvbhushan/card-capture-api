from datetime import datetime, timezone
from typing import Dict, Any, List

def insert_event_db(supabase_client, event_data: Dict[str, Any]):
    return supabase_client.table("events").insert(event_data).execute()

def update_event_db(supabase_client, event_id: str, update_data: Dict[str, Any]):
    return supabase_client.table("events").update(update_data).eq("id", event_id).execute()

def archive_events_db(supabase_client, event_ids: List[str]):
    timestamp = datetime.now(timezone.utc).isoformat()
    update_payload = {
        "status": "archived",
        "updated_at": timestamp
    }
    return supabase_client.table('events') \
        .update(update_payload) \
        .in_("id", event_ids) \
        .execute()

def delete_event_and_cards_db(supabase_client, event_id: str):
    reviewed = supabase_client.table("reviewed_data").delete().eq("event_id", event_id).execute()
    extracted = supabase_client.table("extracted_data").delete().eq("event_id", event_id).execute()
    event = supabase_client.table("events").delete().eq("id", event_id).execute()
    return reviewed, extracted, event 