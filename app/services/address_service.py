import json
from datetime import datetime, timezone
from typing import Dict, Any, Optional
from app.services.document_service import validate_address_with_google, validate_zip_code
from app.core.clients import gmaps_client
from app.utils.retry_utils import log_debug

def validate_and_enhance_address(fields: Dict[str, Any]) -> Dict[str, Any]:
    """
    Post-processing address validation that enhances but never overwrites good data
    
    Args:
        fields: Field data after Gemini processing
        
    Returns:
        Enhanced field data with validated address components
    """
    log_debug("=== ADDRESS VALIDATION START ===", service="address")
    
    # Extract current address components
    address = fields.get('address', {}).get('value', '')
    city = fields.get('city', {}).get('value', '')
    state = fields.get('state', {}).get('value', '')
    zip_code = fields.get('zip_code', {}).get('value', '')
    
    log_debug("Current address components", {
        "address": address,
        "city": city,
        "state": state,
        "zip_code": zip_code
    }, service="address")
    
    # Check required fields first
    for field_name in ['address', 'city', 'state', 'zip_code']:
        if field_name in fields:
            field_data = fields[field_name]
            # Only mark required fields for review
            if field_data.get('required', False):
                if not field_data.get('value') or field_data.get('value', '').strip() == '':
                    field_data['requires_human_review'] = True
                    field_data['review_notes'] = f"Required {field_name} field is empty"
                    field_data['review_confidence'] = 0.3
                else:
                    # If field has a value, don't mark for review based on confidence
                    field_data['requires_human_review'] = False
                    field_data['review_notes'] = ""
            else:
                # Clear any review flags for non-required fields
                field_data['requires_human_review'] = False
                field_data['review_notes'] = ""
    
    # Only proceed with Google Maps validation if we have a zip code
    if zip_code:
        try:
            # First try zip code validation to get city and state
            zip_validation = validate_zip_code(zip_code)
            if zip_validation:
                # Enhance city if missing or low confidence
                if 'city' in zip_validation and _should_enhance_field(fields.get('city', {}), zip_validation['city']):
                    log_debug(f"Enhancing city: '{city}' -> '{zip_validation['city']}'", service="address")
                    original_city = fields.get('city', {})
                    fields['city'] = _create_enhanced_field(
                        zip_validation['city'],
                        "zip_validation",
                        "City validated from zip code",
                        preserve_field_requirements=original_city
                    )
                    # Clear review flag since we validated it
                    fields['city']['requires_human_review'] = False
                    fields['city']['review_notes'] = ""
                
                # Enhance state if missing or low confidence
                if 'state' in zip_validation and _should_enhance_field(fields.get('state', {}), zip_validation['state']):
                    log_debug(f"Enhancing state: '{state}' -> '{zip_validation['state']}'", service="address")
                    original_state = fields.get('state', {})
                    fields['state'] = _create_enhanced_field(
                        zip_validation['state'],
                        "zip_validation",
                        "State validated from zip code",
                        preserve_field_requirements=original_state
                    )
                    # Clear review flag since we validated it
                    fields['state']['requires_human_review'] = False
                    fields['state']['review_notes'] = ""
            
            # Then try full address validation
            validated_address = validate_address_with_google(
                address,
                city or (zip_validation.get('city', '') if zip_validation else ''),
                state or (zip_validation.get('state', '') if zip_validation else ''),
                zip_code
            )
            
            if validated_address and _should_enhance_field(fields.get('address', {}), validated_address):
                log_debug(f"Enhancing address: '{address}' -> '{validated_address}'", service="address")
                fields['address'] = _create_enhanced_field(
                    validated_address,
                    "address_validation",
                    "Address validated from Google Maps"
                )
                # Clear review flag since we validated it
                fields['address']['requires_human_review'] = False
                fields['address']['review_notes'] = ""
            elif address:
                # We have an address but Google Maps couldn't validate it
                log_debug(f"Address '{address}' could not be validated by Google Maps", service="address")
                if 'address' in fields and fields['address'].get('required', False):
                    fields['address']['requires_human_review'] = True
                    fields['address']['review_notes'] = "Required address field could not be validated by Google Maps"
                    fields['address']['review_confidence'] = 0.3
            # Update the address field with the validated street address from Google Maps
            if validated_address and 'street_address' in validated_address:
                log_debug(f"Updating address with validated street address: '{validated_address['street_address']}'", service="address")
                fields['address'] = _create_enhanced_field(
                    validated_address['street_address'],
                    "address_validation",
                    "Address validated from Google Maps"
                )
                fields['address']['requires_human_review'] = False
                fields['address']['review_notes'] = ""
        except Exception as e:
            log_debug(f"Google Maps validation failed: {str(e)}", service="address")
            # If validation failed and address is required, mark it for review
            if 'address' in fields and fields['address'].get('required', False):
                fields['address']['requires_human_review'] = True
                fields['address']['review_notes'] = "Required address field could not be validated by Google Maps"
                fields['address']['review_confidence'] = 0.3
            _mark_address_fields_for_review_if_missing(fields)
            # Also check for obviously invalid addresses
            _check_for_invalid_addresses(fields)
    else:
        log_debug("No valid zip code for validation", service="address")
        _mark_address_fields_for_review_if_missing(fields)
        # Also check for obviously invalid addresses
        _check_for_invalid_addresses(fields)
    
    log_debug("=== ADDRESS VALIDATION COMPLETE ===", service="address")
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

def _create_enhanced_field(value: str, source: str, notes: str, preserve_field_requirements: Dict[str, Any] = None) -> Dict[str, Any]:
    """
    Create a field with enhanced data
    
    Args:
        value: The enhanced value
        source: Where the enhancement came from
        notes: Notes about the enhancement
        preserve_field_requirements: Original field data to preserve enabled/required status
        
    Returns:
        Enhanced field data
    """
    enhanced_field = {
        'value': value,
        'confidence': 0.95,  # High confidence for validated data
        'source': source,
        'notes': notes,
        'requires_human_review': False,
        'review_notes': ""
    }
    
    # Preserve enabled and required status from original field
    if preserve_field_requirements:
        if 'enabled' in preserve_field_requirements:
            enhanced_field['enabled'] = preserve_field_requirements['enabled']
        if 'required' in preserve_field_requirements:
            enhanced_field['required'] = preserve_field_requirements['required']
    
    return enhanced_field

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
        
        # Only mark for review if required and empty
        if is_required and (not field_value or field_value.strip() == ""):
            field_data['requires_human_review'] = True
            field_data['review_notes'] = f"Required {field_name} field could not be validated"
            log_debug(f"Marked {field_name} for review: required but missing", service="address")

def _check_for_invalid_addresses(fields: Dict[str, Any]) -> None:
    """
    Check for obviously invalid street addresses that should be flagged for review
    
    Args:
        fields: Field data to check and update
    """
    if 'address' not in fields:
        return
        
    address_field = fields['address']
    
    # Handle case where address_field is None
    if address_field is None:
        return
        
    # Get the address value and handle None case
    raw_address_value = address_field.get('value', '')
    if raw_address_value is None:
        return
        
    address_value = raw_address_value.strip()
    address_lower = address_value.lower()
    
    # Common patterns that indicate invalid addresses
    invalid_patterns = [
        'n/a', 'na', 'none', 'unknown', 'null', 'nil',
        'see above', 'same as above', 'ditto',
        '123 main st', '123 main street',  # Generic placeholder addresses
        'test', 'testing', 'example'
    ]
    
    # Check if address contains invalid patterns
    for pattern in invalid_patterns:
        if pattern in address_lower:
            address_field['requires_human_review'] = True
            address_field['review_notes'] = f"Address appears to be placeholder or invalid: '{address_value}'"
            address_field['review_confidence'] = 0.2
            log_debug(f"Address flagged for invalid pattern '{pattern}': {address_value}", service="address")
            return
    
    # Check for incomplete addresses missing street numbers
    import re
    
    # Look for street number at the beginning of the address
    # Street number patterns: digits (possibly followed by letter like 123A)
    street_number_pattern = r'^\s*\d+[A-Za-z]?\s+'
    
    if not re.match(street_number_pattern, address_value):
        # No street number found - this is likely an incomplete address
        address_field['requires_human_review'] = True
        address_field['review_notes'] = f"Address appears incomplete - missing street number: '{address_value}'"
        address_field['review_confidence'] = 0.3
        log_debug(f"Address flagged for missing street number: {address_value}", service="address")
        return
    
    # Additional check for very short addresses that are likely incomplete
    if len(address_value.strip()) < 5:
        address_field['requires_human_review'] = True
        address_field['review_notes'] = f"Address too short or incomplete: '{address_value}'"
        address_field['review_confidence'] = 0.2
        log_debug(f"Address flagged for being too short: {address_value}", service="address")
        return

def validate_address_with_google_maps(address: str, city: str, state: str, zip_code: str):
    if not gmaps_client:
        log_debug("Google Maps client not initialized", service="address")
        return None

    if not zip_code:
        log_debug("Zip Code missing for Google Maps validation", service="address")
        return None
    
    # Construct full address string for validation  
    full_address_query = f"{address}, {city}, {state} {zip_code}"
    log_debug(f"Validating via Google Maps (Primary): {full_address_query}", service="address")

    try:
        # Use geocoding to validate the address
        geocode_result = gmaps_client.geocode(full_address_query)
        
        if geocode_result:
            # Extract the first result
            result = geocode_result[0]
            formatted_address = result.get('formatted_address', '')
            geometry = result.get('geometry', {})
            location = geometry.get('location', {})
            
            log_debug("Google Maps validation successful", {
                "original_query": full_address_query,
                "formatted_address": formatted_address,
                "lat": location.get('lat'),
                "lng": location.get('lng')
            }, service="address")
            
            return {
                "is_valid": True,
                "formatted_address": formatted_address,
                "latitude": location.get('lat'),
                "longitude": location.get('lng'),
                "place_id": result.get('place_id'),
                "confidence": "high"  # Google Maps geocoding generally has high confidence
            }
        else:
            log_debug("Google Maps found no results for address", {"query": full_address_query}, service="address")
            return {
                "is_valid": False,
                "error": "Address not found in Google Maps",
                "confidence": "low"
            }
            
    except Exception as e:
        log_debug(f"Google Maps validation error: {str(e)}", {"query": full_address_query}, service="address")
        return {
            "is_valid": False,
            "error": f"Google Maps API error: {str(e)}",
            "confidence": "unknown"
        } 