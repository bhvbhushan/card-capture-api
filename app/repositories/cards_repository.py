from typing import List, Dict, Any, Union
from datetime import datetime, timezone

def get_cards_db(supabase_client, event_id: Union[str, None] = None) -> List[Dict[str, Any]]:
    print(" Rcvd /cards request")
    if event_id:
        print(f" Filtering by event_id: {event_id}")
    reviewed_query = supabase_client.table("reviewed_data").select("*")
    if event_id:
        reviewed_query = reviewed_query.eq("event_id", event_id)
    reviewed_response = reviewed_query.execute()
    reviewed_data = reviewed_response.data
    print(f" Found {len(reviewed_data)} reviewed records.")
    filtered_data = [card for card in reviewed_data if not card.get("deleted") and card.get("review_status") != "archived"]
    print(f" Returning {len(filtered_data)} non-deleted, non-archived records.")
    return filtered_data

def archive_cards_db(supabase_client, document_ids: List[str]):
    timestamp = datetime.now(timezone.utc).isoformat()
    update_payload = {
        "review_status": "archived",
        "reviewed_at": timestamp
    }
    result = supabase_client.table('reviewed_data') \
        .update(update_payload) \
        .in_("document_id", document_ids) \
        .execute()
    return result

def mark_as_exported_db(supabase_client, document_ids: List[str]):
    timestamp = datetime.now(timezone.utc).isoformat()
    update_payload = {
        "exported_at": timestamp
    }
    update_response = supabase_client.table("reviewed_data") \
        .update(update_payload) \
        .in_("document_id", document_ids) \
        .execute()
    return update_response

def delete_cards_db(supabase_client, document_ids: List[str]):
    reviewed_response = supabase_client.table("reviewed_data") \
        .delete() \
        .in_("document_id", document_ids) \
        .execute()
    extracted_response = supabase_client.table("extracted_data") \
        .delete() \
        .in_("document_id", document_ids) \
        .execute()
    return reviewed_response, extracted_response 