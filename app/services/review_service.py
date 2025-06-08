import json
from datetime import datetime, timezone
from typing import Dict, Any, Tuple, List
from app.utils.retry_utils import log_debug

# Add at the top of the file
CANONICAL_FIELD_MAP = {
    "birthdate": "date_of_birth",
    "cell_phone": "cell",
    "city_state_zip": "city_state",
    # Add more mappings as needed
}

def determine_review_status(fields: Dict[str, Any]) -> Tuple[str, List[str]]:
    """
    Single function to determine if card needs review based on field analysis
    
    Args:
        fields: Field data with all metadata
        
    Returns:
        Tuple of (review_status, list_of_fields_needing_review)
    """
    log_debug("=== DETERMINING REVIEW STATUS ===", service="review")
    
    fields_needing_review = []
    
    # Check each field for review requirements
    for field_name, field_data in fields.items():
        if not isinstance(field_data, dict):
            continue
            
        # Skip disabled fields
        if not field_data.get("enabled", True):
            continue
            
        # Only process required fields
        if not field_data.get("required", False):
            # Clear any review flags for non-required fields
            field_data["requires_human_review"] = False
            field_data["review_notes"] = ""
            continue
            
        # Check if field is explicitly marked for review
        if field_data.get("requires_human_review", False):
            fields_needing_review.append(field_name)
            log_debug(f"Field {field_name} explicitly marked for review", {
                "reason": field_data.get("review_notes", "No reason provided")
            }, service="review")
            continue
            
        # Check required field rules
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
            log_debug(f"Field {field_name} marked for review: empty required field", service="review")
            continue
            
        # Required field has low confidence
        if effective_confidence < 0.7:
            fields_needing_review.append(field_name)
            field_data["requires_human_review"] = True
            field_data["review_notes"] = f"Required field has low confidence ({effective_confidence:.2f})"
            log_debug(f"Field {field_name} marked for review: low confidence", service="review")
            continue
    
    # Determine final status
    if fields_needing_review:
        review_status = "needs_human_review"
        log_debug(f"Card needs review - {len(fields_needing_review)} fields flagged", service="review")
    else:
        review_status = "reviewed"
        log_debug("Card does not need review - all fields valid", service="review")
    
    log_debug("Review determination complete", {
        "status": review_status,
        "fields_needing_review": fields_needing_review
    }, service="review")
    
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
    log_debug("=== VALIDATING FIELD DATA ===", service="review")
    
    # Canonicalize field keys before validation
    fields = canonicalize_fields(fields)
    
    for field_name, field_data in fields.items():
        if not isinstance(field_data, dict):
            continue
            
        field_value = field_data.get("value", "")
        
        # Clean up common issues
        if field_value:
            # Remove "N/A" values (only for string values)
            if isinstance(field_value, str) and field_value.upper() in ["N/A", "NA", "NONE", "NULL"]:
                field_data["value"] = ""
                log_debug(f"Cleaned N/A value from {field_name}", service="review")
                
            # Validate phone format
            elif field_name == "cell" and field_value:
                cleaned_phone = _validate_phone_format(field_value)
                if cleaned_phone != field_value:
                    field_data["value"] = cleaned_phone
                    log_debug(f"Formatted phone: {field_value} -> {cleaned_phone}", service="review")
                    
            # Validate date format
            elif field_name == "date_of_birth" and field_value:
                cleaned_date = _validate_date_format(field_value)
                if cleaned_date != field_value:
                    field_data["value"] = cleaned_date
                    log_debug(f"Formatted date: {field_value} -> {cleaned_date}", service="review")
    
    log_debug("Field validation complete", service="review")
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