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