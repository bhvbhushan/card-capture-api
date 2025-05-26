import json
import traceback
from typing import Dict, Any, Optional
from app.core.clients import gmaps_client

# --- Address Validation ---
def validate_address_with_google(address: str, zip_code: str) -> Optional[Dict[str, Any]]:
    if not gmaps_client:
        print("ℹ️ Google Maps client not initialized.")
        return None
    if not zip_code:
        print("ℹ️ Zip Code missing for Google Maps validation.")
        return None
    geocode_result = None
    queried_by_zip_only = False
    full_address_query = f"{address}, {zip_code}" if address else zip_code
    print(f"🗺️ Validating via Google Maps (Primary): {full_address_query}")
    try:
        geocode_result = gmaps_client.geocode(full_address_query)
    except Exception as e:
        print(f"❌ Error during primary Google Maps query: {e}")
        traceback.print_exc()
        geocode_result = None
    if not geocode_result and address:
        print(f"ℹ️ Primary validation failed for '{full_address_query}'. Trying fallback with Zip Code only: {zip_code}")
        try:
            geocode_result = gmaps_client.geocode(zip_code)
            if geocode_result:
                queried_by_zip_only = True
                print(f"✅ Google Maps fallback query successful for Zip: {zip_code}")
        except Exception as e:
            print(f"❌ Error during fallback Google Maps query: {e}")
            traceback.print_exc()
            return None
    if geocode_result:
        result = geocode_result[0]
        print(f"✅ Raw Google Maps response: {json.dumps(result, indent=2)}")
        components = result.get('address_components', [])
        location_type = result.get('geometry', {}).get('location_type', 'UNKNOWN')
        partial_match_flag = result.get('partial_match', False)
        parsed = {
            "street_number": next((c['long_name'] for c in components if 'street_number' in c['types']), None),
            "route": next((c['long_name'] for c in components if 'route' in c['types']), None),
            "city": next((c['long_name'] for c in components if 'locality' in c['types']), None),
            "state": next((c['short_name'] for c in components if 'administrative_area_level_1' in c['types']), None),
            "zip": next((c['long_name'] for c in components if 'postal_code' in c['types']), None),
            "zip_suffix": next((c['long_name'] for c in components if 'postal_code_suffix' in c['types']), None),
            "formatted": result.get('formatted_address')
        }
        street_address_parts = [parsed["street_number"], parsed["route"]]
        parsed["street_address"] = " ".join(filter(None, street_address_parts))
        if parsed["zip"] and parsed["zip_suffix"]:
            parsed["zip"] = f"{parsed['zip']}-{parsed['zip_suffix']}"
        validation_data = {
            "street_address": str(parsed["street_address"] or ''),
            "city": str(parsed["city"] or ''),
            "state": str(parsed["state"] or ''),
            "zip": str(parsed["zip"] or ''),
            "formatted": str(parsed["formatted"] or ''),
            "location_type": location_type,
            "partial_match": partial_match_flag,
            "queried_by_zip_only": queried_by_zip_only
        }
        if validation_data["zip"] or (validation_data["city"] and validation_data["state"]):
            print(f"✅ Google Maps validation successful: {validation_data['formatted']} (Type: {location_type}, Partial: {partial_match_flag}, ZipOnlyQuery: {queried_by_zip_only})")
            return validation_data
        else:
            print(f"⚠️ Google Maps result missing essential components (City/State/Zip). Query: {full_address_query}")
            return None
    else:
        print(f"⚠️ Address/Zip not found by Google Maps after fallback: {full_address_query}")
        return None

def validate_address_components(address: Optional[str], city: Optional[str], state: Optional[str], zip_code: Optional[str]) -> Dict[str, Any]:
    if not gmaps_client:
        return {
            "validated": {},
            "confidence": 0.30,
            "requires_review": True,
            "review_notes": "Google Maps client not available",
            "auto_filled": []
        }
    auto_filled = []
    validated_data = {
        "street_address": "",
        "city": "",
        "state": "",
        "zip": ""
    }
    zip_code = str(zip_code).strip() if zip_code else ""
    city = str(city).strip() if city else ""
    state = str(state).strip().upper() if state else ""
    address = str(address).strip() if address else ""
    if zip_code and len(zip_code) >= 5:
        print(f"🔍 Validating via zip code: {zip_code}")
        zip_validation = validate_address_with_google("", zip_code)
        if zip_validation:
            print(f"✅ Zip validation response: {json.dumps(zip_validation, indent=2)}")
            validated_data["city"] = zip_validation["city"]
            validated_data["state"] = zip_validation["state"]
            validated_data["zip"] = zip_validation["zip"]
            if not city: auto_filled.append("city")
            if not state: auto_filled.append("state")
    requires_review = False
    review_notes = []
    if address:
        print(f"🔍 Validating full address: {address}")
        # First try validating with just the zip code
        full_validation = validate_address_with_google(address, zip_code)
        if not full_validation or not full_validation["street_address"]:
            # If that fails, try with city/state context
            location_context = f"{validated_data['city']}, {validated_data['state']} {validated_data['zip']}"
            print(f"⚠️ Primary validation failed, trying with context: {location_context}")
            full_validation = validate_address_with_google(address, location_context)
        
        if full_validation and full_validation["street_address"]:
            validated_data["street_address"] = full_validation["street_address"]
            print(f"✅ Full address validated: {full_validation['street_address']}")
        else:
            requires_review = True
            review_notes.append("Could not verify street address")
            # Preserve the original address when Google Maps returns empty street address
            validated_data["street_address"] = address
            print(f"⚠️ Could not verify street address, preserving original: {address}")
    else:
        requires_review = True
        review_notes.append("Missing street address")
    return {
        "validated": validated_data,
        "confidence": 0.95 if not requires_review else 0.3,
        "requires_review": requires_review,
        "review_notes": "; ".join(review_notes) if review_notes else "",
        "auto_filled": auto_filled
    } 