import json
from datetime import datetime, timezone
from typing import Dict, Any
from app.core.clients import supabase_client

def log_settings_debug(message: str, data: Any = None):
    """Write debug message and optional data to settings_debug.log"""
    timestamp = datetime.now(timezone.utc).isoformat()
    with open('settings_debug.log', 'a') as f:
        f.write(f"\n[{timestamp}] {message}\n")
        if data:
            if isinstance(data, (dict, list)):
                f.write(json.dumps(data, indent=2))
            else:
                f.write(str(data))
            f.write("\n")

def get_field_requirements(school_id: str) -> Dict[str, Dict[str, bool]]:
    """
    Get field requirements from school settings
    
    Args:
        school_id: School ID to get settings for
        
    Returns:
        Dict with format: {"field_name": {"enabled": bool, "required": bool}}
    """
    log_settings_debug("=== GETTING FIELD REQUIREMENTS ===")
    log_settings_debug(f"School ID: {school_id}")
    
    try:
        # Get school settings from database
        school_query = supabase_client.table("schools").select("card_fields").eq("id", school_id).maybe_single().execute()
        
        if school_query and school_query.data:
            card_fields = school_query.data.get("card_fields", {})
            log_settings_debug("Found school settings", card_fields)
            return card_fields
        else:
            log_settings_debug("No school settings found, returning empty dict")
            return {}
            
    except Exception as e:
        log_settings_debug(f"ERROR getting field requirements: {str(e)}")
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
    log_settings_debug("=== APPLYING FIELD REQUIREMENTS ===")
    log_settings_debug("Input fields", list(fields.keys()))
    log_settings_debug("Requirements", requirements)
    
    # Update existing fields with requirements
    for field_name, field_data in fields.items():
        if field_name in requirements:
            field_settings = requirements[field_name]
            field_data["enabled"] = field_settings.get("enabled", True)
            field_data["required"] = field_settings.get("required", False)
            log_settings_debug(f"Updated {field_name}", {
                "enabled": field_data["enabled"],
                "required": field_data["required"]
            })
        else:
            # Default settings for fields not in requirements
            field_data["enabled"] = True
            field_data["required"] = False
            log_settings_debug(f"Default settings for {field_name}")
    
    # Add missing required fields
    for field_name, field_settings in requirements.items():
        if field_settings.get("required", False) and field_name not in fields:
            log_settings_debug(f"Adding missing required field: {field_name}")
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
    
    log_settings_debug("Final fields", list(fields.keys()))
    return fields

def sync_field_requirements(school_id: str, detected_fields: list) -> Dict[str, Dict[str, bool]]:
    """
    Sync detected fields with school settings, adding any new fields with defaults
    
    Args:
        school_id: School ID to update
        detected_fields: List of field names detected by DocAI
        
    Returns:
        Updated field requirements
    """
    log_settings_debug("=== SYNCING FIELD REQUIREMENTS ===")
    log_settings_debug(f"School ID: {school_id}")
    log_settings_debug("Detected fields", detected_fields)
    
    try:
        # Get current school settings
        current_requirements = get_field_requirements(school_id)
        
        # Add any new fields with default settings
        updated = False
        for field_name in detected_fields:
            if field_name not in current_requirements:
                current_requirements[field_name] = {
                    "enabled": True,
                    "required": False
                }
                updated = True
                log_settings_debug(f"Added new field {field_name} with defaults")
        
        # Update school record if we added new fields
        if updated:
            update_payload = {
                "id": school_id,
                "card_fields": current_requirements
            }
            
            supabase_client.table("schools").update(update_payload).eq("id", school_id).execute()
            log_settings_debug("Updated school settings in database")
        
        return current_requirements
        
    except Exception as e:
        log_settings_debug(f"ERROR syncing field requirements: {str(e)}")
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