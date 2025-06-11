import json
from datetime import datetime, timezone
from typing import Dict, Any, List
from app.core.clients import supabase_client
from app.utils.retry_utils import log_debug
from app.utils.field_utils import get_combined_fields_to_exclude

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
            
            # Filter out combined fields that should not be in final data
            combined_fields = get_combined_fields_to_exclude()
            filtered_card_fields_array = [f for f in card_fields_array if f["key"] not in combined_fields]
            
            # Convert array to dict for internal use
            card_fields = {f["key"]: {"enabled": f.get("enabled", True), "required": f.get("required", False)} for f in filtered_card_fields_array}
            
            log_debug("Found school settings (after filtering combined fields)", card_fields, service="settings")
            if len(card_fields_array) != len(filtered_card_fields_array):
                log_debug(f"Filtered out {len(card_fields_array) - len(filtered_card_fields_array)} combined fields", service="settings")
            
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

        # Filter detected fields to exclude combined fields
        combined_fields = get_combined_fields_to_exclude()
        filtered_detected_fields = [f for f in detected_fields if f not in combined_fields]

        # Add any new fields at the end (excluding combined fields)
        for field_name in filtered_detected_fields:
            if field_name not in existing_keys:
                card_fields_array.append({
                    "key": field_name,
                    "enabled": True,
                    "required": False
                })
                updated = True
                log_debug(f"Added new field {field_name} with defaults", service="settings")

        # Remove any combined fields from existing settings
        original_length = len(card_fields_array)
        card_fields_array = [f for f in card_fields_array if f["key"] not in combined_fields]
        if len(card_fields_array) < original_length:
            updated = True
            log_debug(f"Removed {original_length - len(card_fields_array)} combined fields from school settings", service="settings")

        if updated:
            update_payload = {
                "id": school_id,
                "card_fields": card_fields_array
            }
            supabase_client.table("schools").update(update_payload).eq("id", school_id).execute()
            log_debug("Updated school settings in database", service="settings")

        # Return as dict for internal use (already filtered)
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
        'major',
        'gender'
    ]

def sync_field_types_and_options(school_id: str, detected_field_info: Dict[str, Dict[str, Any]]) -> Dict[str, Dict[str, bool]]:
    """
    Sync detected field types and options with school settings
    
    Args:
        school_id: School ID
        detected_field_info: Field information from Gemini with field_type and detected_options
        
    Returns:
        Updated field requirements dict
    """
    log_debug("=== SYNCING FIELD TYPES AND OPTIONS ===", service="settings")
    log_debug(f"School ID: {school_id}", service="settings")
    log_debug("Detected field info", {
        field_name: {
            "field_type": info.get("field_type", "text"),
            "options_count": len(info.get("detected_options", []))
        }
        for field_name, info in detected_field_info.items()
    }, service="settings")

    try:
        # Get current school settings as array
        school_query = supabase_client.table("schools").select("card_fields").eq("id", school_id).maybe_single().execute()
        card_fields_array = school_query.data.get("card_fields") or []
        
        updated = False
        
        # Update existing fields with type information and options
        for field_config in card_fields_array:
            field_key = field_config["key"]
            if field_key in detected_field_info:
                field_info = detected_field_info[field_key]
                
                # Update field type if not already set
                detected_type = field_info.get("field_type", "text")
                if not field_config.get("field_type") and detected_type != "text":
                    field_config["field_type"] = detected_type
                    updated = True
                    log_debug(f"Updated field type for {field_key}: {detected_type}", service="settings")
                
                # Update options for select fields
                detected_options = field_info.get("detected_options", [])
                if detected_type in ["select", "checkbox"] and detected_options:
                    current_options = field_config.get("options", [])
                    # Merge new options with existing ones (preserve user customizations)
                    merged_options = list(set(current_options + detected_options))
                    if merged_options != current_options:
                        field_config["options"] = sorted(merged_options)  # Sort for consistency
                        updated = True
                        log_debug(f"Updated options for {field_key}: {merged_options}", service="settings")
        
        # Add any new fields with their type information
        existing_keys = {f["key"] for f in card_fields_array}
        combined_fields = get_combined_fields_to_exclude()
        
        for field_name, field_info in detected_field_info.items():
            if field_name not in existing_keys and field_name not in combined_fields:
                new_field = {
                    "key": field_name,
                    "enabled": True,
                    "required": False,
                    "field_type": field_info.get("field_type", "text"),
                }
                
                # Add options for select/checkbox fields
                detected_options = field_info.get("detected_options", [])
                if detected_options and field_info.get("field_type") in ["select", "checkbox"]:
                    new_field["options"] = sorted(detected_options)
                
                card_fields_array.append(new_field)
                updated = True
                log_debug(f"Added new field {field_name} with type {new_field['field_type']}", service="settings")
        
        # Save if updated
        if updated:
            update_payload = {
                "id": school_id,
                "card_fields": card_fields_array
            }
            supabase_client.table("schools").update(update_payload).eq("id", school_id).execute()
            log_debug("Updated school card_fields with type information", service="settings")
        
        # Return as dict for internal use
        return {f["key"]: {"enabled": f.get("enabled", True), "required": f.get("required", False)} for f in card_fields_array}
        
    except Exception as e:
        log_debug(f"ERROR syncing field types and options: {str(e)}", service="settings")
        return {} 