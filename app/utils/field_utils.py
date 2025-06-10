# Field utilities for processing card data

def filter_combined_fields(fields: dict) -> dict:
    """
    Remove combined fields that have been split into individual components.
    These fields should not be saved to the final reviewed_data table.
    
    Combined fields to exclude:
    - city_state: Gets split into city + state
    - city_state_zip: Gets split into city + state + zip_code
    - citystatezip: Gets split into city + state + zip_code
    - address_line: Gets split into individual address components
    - high_school_class_rank: Gets split into high_school + class_rank
    
    Args:
        fields: Dictionary of field data
        
    Returns:
        Filtered dictionary with combined fields removed
    """
    # Define fields that should be excluded from final data
    COMBINED_FIELDS_TO_EXCLUDE = [
        'city_state',
        'city_state_zip', 
        'citystatezip',
        'address_line',
        'high_school_class_rank',
        'city_state_country',  # In case this appears
        'full_address',        # In case this appears
        'address_combined',    # In case this appears
    ]
    
    # Create a copy of fields without the combined fields
    filtered_fields = {}
    
    for field_name, field_data in fields.items():
        if field_name not in COMBINED_FIELDS_TO_EXCLUDE:
            filtered_fields[field_name] = field_data
    
    return filtered_fields

def get_individual_address_fields():
    """
    Get the list of individual address fields that should be preserved.
    
    Returns:
        List of individual address field names
    """
    return ['address', 'city', 'state', 'zip_code']

def get_combined_fields_to_exclude():
    """
    Get the list of combined fields that should be excluded from final data.
    
    Returns:
        List of combined field names to exclude
    """
    return [
        'city_state',
        'city_state_zip', 
        'citystatezip',
        'address_line',
        'high_school_class_rank',
        'city_state_country',
        'full_address',
        'address_combined',
    ]

def generate_field_label(field_key: str) -> str:
    """Convert field keys to user-friendly display labels"""
    
    # Special cases for common field mappings
    special_mappings = {
        'cell': 'Phone Number',
        'date_of_birth': 'Birthday', 
        'zip_code': 'Zip Code',
        'high_school': 'High School',
        'entry_term': 'Entry Term',
        'permission_to_text': 'Permission to Text',
        'preferred_first_name': 'Preferred Name',
        'students_in_class': 'Students in Class',
        'class_rank': 'Class Rank',
        'student_type': 'Student Type',
        'mapped_major': 'Mapped Major',
        'gpa': 'GPA'
    }
    
    # Return special mapping if it exists
    if field_key in special_mappings:
        return special_mappings[field_key]
    
    # Convert snake_case to Title Case
    # Replace underscores with spaces and capitalize each word
    words = field_key.replace('_', ' ').split()
    return ' '.join(word.capitalize() for word in words)


def validate_field_key(field_key: str) -> bool:
    """Validate that a field key is properly formatted"""
    if not field_key or not isinstance(field_key, str):
        return False
    
    # Field keys should be lowercase, alphanumeric, with underscores
    import re
    return bool(re.match(r'^[a-z][a-z0-9_]*$', field_key))


def get_field_consolidation_mapping() -> dict:
    """
    Get mapping of legacy/variant field names to canonical field names
    This helps consolidate duplicate fields with different names
    
    Returns:
        Dictionary mapping old field names to canonical field names
    """
    return {
        # Date of birth variations
        'birthdate': 'date_of_birth',
        'dob': 'date_of_birth',
        'birth_date': 'date_of_birth',
        'birthday': 'date_of_birth',
        
        # Phone number variations  
        'cell_phone': 'cell',
        'phone': 'cell',
        'phone_number': 'cell',
        'mobile': 'cell',
        'mobile_phone': 'cell',
        'cellphone': 'cell',
        
        # Email variations
        'email_address': 'email',
        'e_mail': 'email',
        'emailaddress': 'email',
        
        # Address variations
        'street_address': 'address',
        'home_address': 'address',
        'mailing_address': 'address',
        
        # Name variations
        'student_name': 'name',
        'full_name': 'name',
        'fullname': 'name',
        
        # Major variations
        'program': 'major',
        'degree': 'major',
        'field_of_study': 'major',
        'major_program': 'major',
        
        # High school variations
        'highschool': 'high_school',
        'high_school_name': 'high_school',
        'previous_school': 'high_school',
        
        # Entry term variations
        'entryterm': 'entry_term',
        'entry_semester': 'entry_term',
        'start_term': 'entry_term',
        
        # Student type variations
        'studenttype': 'student_type',
        'student_category': 'student_type',
        'enrollment_type': 'student_type'
    }


def consolidate_field_keys(fields: list) -> list:
    """
    Consolidate duplicate fields that represent the same logical field
    
    Args:
        fields: List of field configurations with 'key', 'enabled', 'required', etc.
        
    Returns:
        Consolidated list with duplicate fields merged
    """
    from app.utils.retry_utils import log_debug
    
    consolidation_map = get_field_consolidation_mapping()
    canonical_fields = {}
    
    # 🔍 TRACK CRITICAL FIELDS: Check for critical field consolidation
    critical_fields = ["cell", "date_of_birth", "cell_phone", "birthday", "birthdate", "phone", "phone_number"]
    critical_consolidation_info = {}
    
    log_debug("Starting field consolidation", {
        "input_fields": [f.get('key') for f in fields],
        "consolidation_rules": len(consolidation_map)
    }, service="field_consolidation")
    
    for field in fields:
        if not isinstance(field, dict) or 'key' not in field:
            continue
            
        field_key = field.get('key', '')
        if not field_key:
            continue
        
        # Get canonical field name
        canonical_key = consolidation_map.get(field_key, field_key)
        
        # Track critical field consolidations
        if field_key in critical_fields or canonical_key in critical_fields:
            critical_consolidation_info[field_key] = {
                "original_key": field_key,
                "canonical_key": canonical_key,
                "was_consolidated": field_key != canonical_key,
                "enabled": field.get('enabled', False),
                "required": field.get('required', False)
            }
        
        if canonical_key in canonical_fields:
            # Merge with existing canonical field
            existing = canonical_fields[canonical_key]
            
            # Keep enabled if either is enabled
            existing['enabled'] = existing.get('enabled', False) or field.get('enabled', False)
            
            # Keep required if either is required  
            existing['required'] = existing.get('required', False) or field.get('required', False)
            
            # Keep the better label if available
            if field.get('label') and not existing.get('label'):
                existing['label'] = field['label']
                
            log_debug(f"Merged duplicate field {field_key} into {canonical_key}", {
                "original_key": field_key,
                "canonical_key": canonical_key,
                "enabled": existing['enabled'],
                "required": existing['required']
            }, service="field_consolidation")
            
        else:
            # Add as new canonical field
            canonical_fields[canonical_key] = {
                'key': canonical_key,
                'label': field.get('label') or generate_field_label(canonical_key),
                'enabled': field.get('enabled', True),
                'required': field.get('required', False)
            }
            
            if field_key != canonical_key:
                log_debug(f"Normalized field {field_key} to {canonical_key}", service="field_consolidation")
    
    result = list(canonical_fields.values())
    
    # 🔍 TRACK CRITICAL FIELDS: Log consolidation results
    log_debug("🔍 CRITICAL FIELD CONSOLIDATION RESULTS", critical_consolidation_info, service="field_consolidation")
    
    log_debug("Field consolidation complete", {
        "input_count": len(fields),
        "output_count": len(result),
        "consolidated_fields": [f['key'] for f in result]
    }, service="field_consolidation")
    
    return result 