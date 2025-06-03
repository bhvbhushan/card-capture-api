import json
from datetime import datetime, timezone
from typing import Dict, Any, Optional
from app.services.document_service import validate_address_with_google
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
    
    # Only attempt validation if we have a zip code
    if zip_code and len(zip_code.strip()) >= 5:
        log_debug("Attempting Google Maps validation with zip code", service="address")
        validation_result = validate_address_with_google(address, zip_code)
        
        if validation_result:
            log_debug("Google Maps validation successful", validation_result, service="address")
            
            # Enhance city if missing or low confidence
            if _should_enhance_field(fields.get('city', {}), validation_result.get('city', '')):
                log_debug(f"Enhancing city: '{city}' -> '{validation_result['city']}'", service="address")
                fields['city'] = _create_enhanced_field(
                    validation_result['city'],
                    "zip_validation",
                    "City validated from zip code"
                )
            
            # Enhance state if missing or low confidence
            if _should_enhance_field(fields.get('state', {}), validation_result.get('state', '')):
                log_debug(f"Enhancing state: '{state}' -> '{validation_result['state']}'", service="address")
                fields['state'] = _create_enhanced_field(
                    validation_result['state'],
                    "zip_validation",
                    "State validated from zip code"
                )
            
            # Enhance zip code if we got a more complete one
            validated_zip = validation_result.get('zip', '')
            if validated_zip and len(validated_zip) > len(zip_code):
                log_debug(f"Enhancing zip: '{zip_code}' -> '{validated_zip}'", service="address")
                fields['zip_code'] = _create_enhanced_field(
                    validated_zip,
                    "zip_validation",
                    "Zip code enhanced from validation"
                )
            
            # Enhance address if missing and we got a street address
            validated_address = validation_result.get('street_address', '')
            if validated_address and _should_enhance_field(fields.get('address', {}), validated_address):
                log_debug(f"Enhancing address: '{address}' -> '{validated_address}'", service="address")
                fields['address'] = _create_enhanced_field(
                    validated_address,
                    "address_validation",
                    "Address validated from Google Maps"
                )
            elif address and not validated_address:
                # We have an address but Google Maps couldn't validate it
                log_debug(f"Address '{address}' could not be validated by Google Maps", service="address")
                if 'address' in fields:
                    fields['address']['requires_human_review'] = True
                    fields['address']['review_notes'] = "Address could not be validated"
                    fields['address']['review_confidence'] = 0.3
        else:
            log_debug("Google Maps validation failed", service="address")
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
    address_value = address_field.get('value', '').lower()
    
    # Common patterns that indicate invalid addresses
    invalid_patterns = [
        'n/a', 'na', 'none', 'unknown', 'null', 'nil',
        'see above', 'same as above', 'ditto',
        '123 main st', '123 main street',  # Generic placeholder addresses
        'test', 'testing', 'example'
    ]
    
    # Check if address contains invalid patterns
    for pattern in invalid_patterns:
        if pattern in address_value:
            address_field['requires_human_review'] = True
            address_field['review_notes'] = f"Address appears to be placeholder or invalid: '{address_field.get('value', '')}'"
            address_field['review_confidence'] = 0.2
            break

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