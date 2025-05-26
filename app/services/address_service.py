import json
from datetime import datetime, timezone
from typing import Dict, Any, Optional
from app.services.document_service import validate_address_with_google

def log_address_debug(message: str, data: Any = None):
    """Write debug message and optional data to address_debug.log"""
    timestamp = datetime.now(timezone.utc).isoformat()
    with open('address_debug.log', 'a') as f:
        f.write(f"\n[{timestamp}] {message}\n")
        if data:
            if isinstance(data, (dict, list)):
                f.write(json.dumps(data, indent=2))
            else:
                f.write(str(data))
            f.write("\n")

def validate_and_enhance_address(fields: Dict[str, Any]) -> Dict[str, Any]:
    """
    Post-processing address validation that enhances but never overwrites good data
    
    Args:
        fields: Field data after Gemini processing
        
    Returns:
        Enhanced field data with validated address components
    """
    log_address_debug("=== ADDRESS VALIDATION START ===")
    
    # Extract current address components
    address = fields.get('address', {}).get('value', '')
    city = fields.get('city', {}).get('value', '')
    state = fields.get('state', {}).get('value', '')
    zip_code = fields.get('zip_code', {}).get('value', '')
    
    log_address_debug("Current address components", {
        "address": address,
        "city": city,
        "state": state,
        "zip_code": zip_code
    })
    
    # Only attempt validation if we have a zip code
    if zip_code and len(zip_code.strip()) >= 5:
        log_address_debug("Attempting Google Maps validation with zip code")
        validation_result = validate_address_with_google(address, zip_code)
        
        if validation_result:
            log_address_debug("Google Maps validation successful", validation_result)
            
            # Enhance city if missing or low confidence
            if _should_enhance_field(fields.get('city', {}), validation_result.get('city', '')):
                log_address_debug(f"Enhancing city: '{city}' -> '{validation_result['city']}'")
                fields['city'] = _create_enhanced_field(
                    validation_result['city'],
                    "zip_validation",
                    "City validated from zip code"
                )
            
            # Enhance state if missing or low confidence
            if _should_enhance_field(fields.get('state', {}), validation_result.get('state', '')):
                log_address_debug(f"Enhancing state: '{state}' -> '{validation_result['state']}'")
                fields['state'] = _create_enhanced_field(
                    validation_result['state'],
                    "zip_validation",
                    "State validated from zip code"
                )
            
            # Enhance zip code if we got a more complete one
            validated_zip = validation_result.get('zip', '')
            if validated_zip and len(validated_zip) > len(zip_code):
                log_address_debug(f"Enhancing zip: '{zip_code}' -> '{validated_zip}'")
                fields['zip_code'] = _create_enhanced_field(
                    validated_zip,
                    "zip_validation",
                    "Zip code enhanced from validation"
                )
            
            # Enhance address if missing and we got a street address
            validated_address = validation_result.get('street_address', '')
            if validated_address and _should_enhance_field(fields.get('address', {}), validated_address):
                log_address_debug(f"Enhancing address: '{address}' -> '{validated_address}'")
                fields['address'] = _create_enhanced_field(
                    validated_address,
                    "address_validation",
                    "Address validated from Google Maps"
                )
            elif address and not validated_address:
                # We have an address but Google Maps couldn't validate it
                log_address_debug(f"Address '{address}' could not be validated by Google Maps")
                if 'address' in fields:
                    fields['address']['requires_human_review'] = True
                    fields['address']['review_notes'] = "Address could not be validated"
                    fields['address']['review_confidence'] = 0.3
        else:
            log_address_debug("Google Maps validation failed")
            _mark_address_fields_for_review_if_missing(fields)
            # Also check for obviously invalid addresses
            _check_for_invalid_addresses(fields)
    else:
        log_address_debug("No valid zip code for validation")
        _mark_address_fields_for_review_if_missing(fields)
        # Also check for obviously invalid addresses
        _check_for_invalid_addresses(fields)
    
    log_address_debug("=== ADDRESS VALIDATION COMPLETE ===")
    return fields

def _should_enhance_field(current_field: Dict[str, Any], new_value: str) -> bool:
    """
    Determine if we should enhance a field with a new value
    
    Args:
        current_field: Current field data
        new_value: New value from validation
        
    Returns:
        True if we should enhance the field
    """
    if not new_value:
        return False
        
    current_value = current_field.get('value', '')
    current_confidence = current_field.get('confidence', 0.0)
    current_review_confidence = current_field.get('review_confidence', 0.0)
    
    # Use the higher confidence score
    effective_confidence = max(current_confidence, current_review_confidence)
    
    # Enhance if field is empty
    if not current_value or current_value.strip() == "":
        return True
        
    # Enhance if field has low confidence
    if effective_confidence < 0.8:
        return True
        
    # Don't enhance if we have good data
    return False

def _create_enhanced_field(value: str, source: str, notes: str) -> Dict[str, Any]:
    """
    Create an enhanced field data structure
    
    Args:
        value: The enhanced value
        source: Source of the enhancement
        notes: Notes about the enhancement
        
    Returns:
        Enhanced field data structure
    """
    return {
        "value": value,
        "confidence": 0.95,  # High confidence for validated data
        "bounding_box": [],
        "source": source,
        "enabled": True,
        "required": False,  # Will be updated by settings
        "requires_human_review": False,  # Validated data doesn't need review
        "review_notes": notes,
        "review_confidence": 0.95
    }

def _mark_address_fields_for_review_if_missing(fields: Dict[str, Any]) -> None:
    """
    Mark address-related fields for review if they're missing and required
    
    Args:
        fields: Field data to check and update
    """
    address_fields = ['address', 'city', 'state', 'zip_code']
    
    for field_name in address_fields:
        if field_name not in fields:
            continue
            
        field_data = fields[field_name]
        field_value = field_data.get('value', '')
        is_required = field_data.get('required', False)
        
        # Mark for review if required and empty
        if is_required and (not field_value or field_value.strip() == ""):
            field_data['requires_human_review'] = True
            field_data['review_notes'] = f"Required {field_name} field could not be validated"
            log_address_debug(f"Marked {field_name} for review: required but missing")

def _check_for_invalid_addresses(fields: Dict[str, Any]) -> None:
    """
    Check for obviously invalid street addresses that should be flagged for review
    
    Args:
        fields: Field data to check and update
    """
    if 'address' not in fields:
        return
        
    address_field = fields['address']
    address_value = address_field.get('value', '').strip()
    
    if not address_value:
        return
        
    # Check for obviously invalid patterns
    invalid_patterns = [
        # No numbers (street addresses should have numbers)
        r'^[A-Za-z\s]+$',  # Only letters and spaces, no numbers
        # Common OCR errors or nonsense
        r'.*[Pp]umes.*',  # "Pumes" is likely OCR error for "Plumes" or similar
        r'.*[Ww]estern [Pp]umes.*',  # Specific case we're seeing
        # Very short addresses (less than 5 characters)
        r'^.{1,4}$',
        # Only special characters
        r'^[^A-Za-z0-9]+$'
    ]
    
    import re
    for pattern in invalid_patterns:
        if re.match(pattern, address_value):
            log_address_debug(f"Address '{address_value}' matches invalid pattern: {pattern}")
            address_field['requires_human_review'] = True
            address_field['review_notes'] = "Address appears to be invalid or incomplete"
            address_field['review_confidence'] = 0.2
            break 