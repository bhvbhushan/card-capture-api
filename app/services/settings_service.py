import json
from datetime import datetime, timezone
from typing import Dict, Any
from app.core.clients import supabase_client
from app.utils.retry_utils import log_debug

def get_field_requirements(school_id: str) -> Dict[str, Dict[str, bool]]:
    """
    Get field requirements from school settings (now as an array)
    """
    log_debug("=== GETTING FIELD REQUIREMENTS ===", service="settings")
    log_debug(f"School ID: {school_id}", service="settings")

    try:
        school_query = supabase_client.table("schools").select("card_fields").eq("id", school_id).maybe_single().execute()
        if school_query and school_query.data:
            card_fields_array = school_query.data.get("card_fields") or []
            # Convert array to dict for internal use
            card_fields = {f["key"]: {"enabled": f.get("enabled", True), "required": f.get("required", False)} for f in card_fields_array}
            log_debug("Found school settings", card_fields, service="settings")
            return card_fields
        else:
            log_debug("No school settings found, returning empty dict", service="settings")
            return {}
    except Exception as e:
        log_debug(f"ERROR getting field requirements: {str(e)}", service="settings")
        return {}

def apply_field_requirements(fields: Dict[str, Any], requirements: Dict[str, Dict[str, bool]]) -> Dict[str, Any]:
    """
    Apply school requirements to field data and add missing required fields
    
    Args:
        fields: Field data from DocAI processing
        requirements: Field requirements from school settings
        
    Returns:
        Updated field data with requirements applied
    """
    log_debug("=== APPLYING FIELD REQUIREMENTS ===", service="settings")
    log_debug("Input fields", list(fields.keys()), service="settings")
    log_debug("Requirements", requirements, service="settings")
    
    # Update existing fields with requirements
    for field_name, field_data in fields.items():
        if field_name in requirements:
            field_settings = requirements[field_name]
            field_data["enabled"] = field_settings.get("enabled", True)
            field_data["required"] = field_settings.get("required", False)
            log_debug(f"Updated {field_name}", {
                "enabled": field_data["enabled"],
                "required": field_data["required"]
            }, service="settings")
        else:
            # Default settings for fields not in requirements
            field_data["enabled"] = True
            field_data["required"] = False
            log_debug(f"Default settings for {field_name}", service="settings")
    
    # Add missing required fields
    for field_name, field_settings in requirements.items():
        if field_settings.get("required", False) and field_name not in fields:
            log_debug(f"Adding missing required field: {field_name}", service="settings")
            fields[field_name] = {
                "value": "",
                "confidence": 0.0,
                "bounding_box": [],
                "source": "missing_required",
                "enabled": field_settings.get("enabled", True),
                "required": True,
                "requires_human_review": True,
                "review_notes": "Required field not detected by DocAI",
                "review_confidence": 0.0
            }
    
    log_debug("Final fields", list(fields.keys()), service="settings")
    return fields

def sync_field_requirements(school_id: str, detected_fields: list) -> Dict[str, Dict[str, bool]]:
    """
    Sync detected fields with school settings, adding any new fields with defaults
    """
    log_debug("=== SYNCING FIELD REQUIREMENTS ===", service="settings")
    log_debug(f"School ID: {school_id}", service="settings")
    log_debug("Detected fields", detected_fields, service="settings")

    try:
        # Get current school settings as array
        school_query = supabase_client.table("schools").select("card_fields").eq("id", school_id).maybe_single().execute()
        card_fields_array = school_query.data.get("card_fields") or []
        existing_keys = {f["key"] for f in card_fields_array}
        updated = False

        # Add any new fields at the end
        for field_name in detected_fields:
            if field_name not in existing_keys:
                card_fields_array.append({
                    "key": field_name,
                    "enabled": True,
                    "required": False
                })
                updated = True
                log_debug(f"Added new field {field_name} with defaults", service="settings")

        # Optionally, remove fields not in detected_fields (if you want to prune)
        # card_fields_array = [f for f in card_fields_array if f["key"] in detected_fields]

        if updated:
            update_payload = {
                "id": school_id,
                "card_fields": card_fields_array
            }
            supabase_client.table("schools").update(update_payload).eq("id", school_id).execute()
            log_debug("Updated school settings in database", service="settings")

        # Return as dict for internal use
        return {f["key"]: {"enabled": f.get("enabled", True), "required": f.get("required", False)} for f in card_fields_array}

    except Exception as e:
        log_debug(f"ERROR syncing field requirements: {str(e)}", service="settings")
        return {}

def get_canonical_field_list() -> list:
    """
    Get the canonical list of fields that the system supports
    
    Returns:
        List of canonical field names
    """
    return [
        'name',
        'preferred_first_name', 
        'date_of_birth',
        'email',
        'cell',
        'permission_to_text',
        'address',
        'city',
        'state',
        'zip_code',
        'high_school',
        'class_rank',
        'students_in_class',
        'gpa',
        'student_type',
        'entry_term',
        'major'
    ] 