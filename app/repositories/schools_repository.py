from fastapi import HTTPException

def get_school_by_id_db(supabase_client, school_id: str):
    response = supabase_client.table("schools") \
        .select("*") \
        .eq("id", school_id) \
        .maybe_single() \
        .execute()
    if not response.data:
        raise HTTPException(status_code=404, detail="School not found.")
    return response.data 