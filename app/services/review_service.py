import json
from datetime import datetime, timezone
from typing import Dict, Any, Tuple, List

# Add at the top of the file
CANONICAL_FIELD_MAP = {
    "birthdate": "date_of_birth",
    "cell_phone": "cell",
    "city_state_zip": "city_state",
    # Add more mappings as needed
}

def log_review_debug(message: str, data: Any = None):
    """Write debug message and optional data to review_debug.log"""
    timestamp = datetime.now(timezone.utc).isoformat()
    with open('review_debug.log', 'a') as f:
        f.write(f"\n[{timestamp}] {message}\n")
        if data:
            if isinstance(data, (dict, list)):
                f.write(json.dumps(data, indent=2))
            else:
                f.write(str(data))
            f.write("\n")

def determine_review_status(fields: Dict[str, Any]) -> Tuple[str, List[str]]:
    """
    Single function to determine if card needs review based on field analysis
    
    Args:
        fields: Field data with all metadata
        
    Returns:
        Tuple of (review_status, list_of_fields_needing_review)
    """
    log_review_debug("=== DETERMINING REVIEW STATUS ===")
    
    fields_needing_review = []
    
    # Check each field for review requirements
    for field_name, field_data in fields.items():
        if not isinstance(field_data, dict):
            continue
            
        # Skip disabled fields
        if not field_data.get("enabled", True):
            continue
            
        # Check if field is explicitly marked for review
        if field_data.get("requires_human_review", False):
            fields_needing_review.append(field_name)
            log_review_debug(f"Field {field_name} explicitly marked for review", {
                "reason": field_data.get("review_notes", "No reason provided")
            })
            continue
            
        # Check required field rules
        if field_data.get("required", False):
            field_value = field_data.get("value", "")
            confidence = field_data.get("confidence", 0.0)
            review_confidence = field_data.get("review_confidence", 0.0)
            
            # Use the higher of the two confidence scores
            effective_confidence = max(confidence, review_confidence)
            
            # Required field is empty
            if not field_value or field_value.strip() == "":
                fields_needing_review.append(field_name)
                field_data["requires_human_review"] = True
                field_data["review_notes"] = "Required field is empty"
                log_review_debug(f"Field {field_name} marked for review: empty required field")
                continue
                
            # Required field has low confidence
            if effective_confidence < 0.7:
                fields_needing_review.append(field_name)
                field_data["requires_human_review"] = True
                field_data["review_notes"] = f"Required field has low confidence ({effective_confidence:.2f})"
                log_review_debug(f"Field {field_name} marked for review: low confidence")
                continue
    
    # Determine final status
    if fields_needing_review:
        review_status = "needs_human_review"
        log_review_debug(f"Card needs review - {len(fields_needing_review)} fields flagged")
    else:
        review_status = "reviewed"
        log_review_debug("Card does not need review - all fields valid")
    
    log_review_debug("Review determination complete", {
        "status": review_status,
        "fields_needing_review": fields_needing_review
    })
    
    return review_status, fields_needing_review

def canonicalize_fields(fields: dict) -> dict:
    """
    Map alternate field names to canonical field names.
    """
    new_fields = {}
    for key, value in fields.items():
        canonical_key = CANONICAL_FIELD_MAP.get(key, key)
        new_fields[canonical_key] = value
    return new_fields

def validate_field_data(fields: Dict[str, Any]) -> Dict[str, Any]:
    """
    Validate and clean field data, applying business rules
    
    Args:
        fields: Field data to validate
        
    Returns:
        Validated and cleaned field data
    """
    log_review_debug("=== VALIDATING FIELD DATA ===")
    
    # Canonicalize field keys before validation
    fields = canonicalize_fields(fields)
    
    for field_name, field_data in fields.items():
        if not isinstance(field_data, dict):
            continue
            
        field_value = field_data.get("value", "")
        
        # Clean up common issues
        if field_value:
            # Remove "N/A" values
            if field_value.upper() in ["N/A", "NA", "NONE", "NULL"]:
                field_data["value"] = ""
                log_review_debug(f"Cleaned N/A value from {field_name}")
                
            # Validate phone format
            elif field_name == "cell" and field_value:
                cleaned_phone = _validate_phone_format(field_value)
                if cleaned_phone != field_value:
                    field_data["value"] = cleaned_phone
                    log_review_debug(f"Formatted phone: {field_value} -> {cleaned_phone}")
                    
            # Validate date format
            elif field_name == "date_of_birth" and field_value:
                cleaned_date = _validate_date_format(field_value)
                if cleaned_date != field_value:
                    field_data["value"] = cleaned_date
                    log_review_debug(f"Formatted date: {field_value} -> {cleaned_date}")
    
    log_review_debug("Field validation complete")
    return fields

def _validate_phone_format(phone: str) -> str:
    """Validate and clean phone format"""
    import re
    
    # Remove all non-digit characters
    digits = re.sub(r'\D', '', phone)
    
    # Format as xxx-xxx-xxxx if we have 10 digits
    if len(digits) == 10:
        return f"{digits[:3]}-{digits[3:6]}-{digits[6:]}"
    elif len(digits) == 11 and digits[0] == '1':
        # Remove leading 1
        digits = digits[1:]
        return f"{digits[:3]}-{digits[3:6]}-{digits[6:]}"
    else:
        return phone  # Return original if we can't format it

def _validate_date_format(date_str: str) -> str:
    """Validate and clean date format"""
    import re
    from datetime import datetime
    
    # Try to parse various date formats and convert to MM/DD/YYYY
    date_patterns = [
        r'(\d{1,2})/(\d{1,2})/(\d{4})',  # MM/DD/YYYY or M/D/YYYY
        r'(\d{1,2})-(\d{1,2})-(\d{4})',  # MM-DD-YYYY or M-D-YYYY
        r'(\d{1,2})\.(\d{1,2})\.(\d{4})', # MM.DD.YYYY or M.D.YYYY
        r'(\d{4})-(\d{1,2})-(\d{1,2})',  # YYYY-MM-DD
    ]
    
    for pattern in date_patterns:
        match = re.match(pattern, date_str.strip())
        if match:
            try:
                if pattern.startswith(r'(\d{4})'):  # YYYY-MM-DD format
                    year, month, day = match.groups()
                else:  # MM/DD/YYYY format
                    month, day, year = match.groups()
                
                # Validate date
                datetime(int(year), int(month), int(day))
                
                # Return in MM/DD/YYYY format with zero padding
                return f"{int(month):02d}/{int(day):02d}/{year}"
                
            except ValueError:
                continue
    
    return date_str  # Return original if we can't parse it 