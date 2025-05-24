import os
import io
import json
import re
import traceback
from datetime import datetime, timezone
from fastapi.responses import JSONResponse
from app.config import GEMINI_MODEL
from app.core.clients import docai_client, project_id, location, gmaps_client, mime_type
import googlemaps
import google.generativeai as genai
from typing import Dict, Any, Optional
from app.core.gemini_prompt import GEMINI_PROMPT_TEMPLATE
import time
import concurrent.futures

ALL_EXPECTED_FIELDS = [
    'name', 'preferred_first_name', 'date_of_birth', 'email', 'cell',
    'permission_to_text', 'address', 'city', 'state', 'zip_code',
    'high_school', 'class_rank', 'students_in_class', 'gpa',
    'student_type', 'entry_term', 'major',
    'city_state']

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
        location_context = f"{validated_data['city']}, {validated_data['state']} {validated_data['zip']}"
        full_validation = validate_address_with_google(address, location_context)
        if full_validation and full_validation["street_address"]:
            validated_data["street_address"] = full_validation["street_address"]
            print(f"✅ Full address validated: {full_validation['street_address']}")
        else:
            requires_review = True
            review_notes.append("Could not verify street address")
            validated_data["street_address"] = address
            print("⚠️ Could not verify street address")
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

# --- Document AI Processing ---
def process_image(image_path: str, processor_id: str, user_id: str = None, school_id: str = None) -> Dict[str, Any]:
    docai_name = f"projects/{project_id}/locations/{location}/processors/{processor_id}"
    if not docai_client or not docai_name:
        raise ValueError("Document AI client not available")
    print(f"🔍 Processing image '{os.path.basename(image_path)}' with Document AI...")
    try:
        with io.open(image_path, "rb") as image:
            image_content = image.read()
        current_mime_type = mime_type
        from google.cloud import documentai_v1 as documentai
        raw_document = documentai.RawDocument(content=image_content, mime_type=current_mime_type)
      
        request = documentai.ProcessRequest(name=docai_name, raw_document=raw_document)
        result = docai_client.process_document(request=request)
        document = result.document
        # Write the full raw Document AI response to worker_debug.log
        with open('worker_debug.log', 'w') as f:
            f.write('=== RAW Document AI API Response (document object) ===\n')
            f.write(str(document))
            f.write('\n=== END RAW Document AI API Response ===\n\n')
        print(f"✅ Document AI OCR processing completed.")
        print("-" * 20, "Document AI Raw Response Start", "-" * 20)
        print("Detected Entities:")
        if document.entities:
            for entity in document.entities:
                print(f"  - Type: {entity.type_}\n    Mention Text: '{entity.mention_text}'\n    Confidence: {entity.confidence:.4f}")
        else:
            print("  No entities detected by the processor.")
        print("-" * 20, "Document AI Raw Response End", "-" * 20)
        processed_dict = {}
        if document.entities:
            for entity in document.entities:
                key = entity.type_
                value = entity.mention_text.strip()
                docai_confidence = entity.confidence
                processed_dict[key] = {"value": value, "vision_confidence": docai_confidence}
            print(f"✅ Formatted {len(processed_dict)} fields found by Document AI.")
            print("Fields found:", json.dumps(processed_dict, indent=2))

            # Always split city_state if present and use as initial city/state
            if 'city_state' in processed_dict:
                city_state_value = processed_dict['city_state']['value']
                parts = [part.strip() for part in city_state_value.split(",")]
                if len(parts) >= 2:
                    processed_dict['city'] = {"value": parts[0], "vision_confidence": processed_dict['city_state']['vision_confidence']}
                    processed_dict['state'] = {"value": parts[1], "vision_confidence": processed_dict['city_state']['vision_confidence']}
                elif len(parts) == 1:
                    processed_dict['city'] = {"value": parts[0], "vision_confidence": processed_dict['city_state']['vision_confidence']}
                    processed_dict['state'] = {"value": "", "vision_confidence": processed_dict['city_state']['vision_confidence']}
                print(f"Split city_state into city: '{processed_dict['city']['value']}' and state: '{processed_dict['state']['value']}'")
                del processed_dict['city_state']
        else:
            print(f"⚠️ No entities found by Document AI.")

        # Get settings for required flags if school_id is provided
        card_fields = {}
        if school_id:
            try:
                from app.core.clients import supabase_client
                school_query = supabase_client.table("schools").select("card_fields").eq("id", school_id).maybe_single().execute()
                if school_query and school_query.data:
                    card_fields = school_query.data.get("card_fields", {})
                    print(f"✅ Retrieved school settings for school {school_id}")
                    print(f"Settings: {json.dumps(card_fields, indent=2)}")
                else:
                    print(f"⚠️ No card_fields in school settings for school {school_id}")
            except Exception as e:
                print(f"⚠️ Error fetching school settings: {e}")
                card_fields = {}

        final_extracted_fields = {}
        for field_key in ALL_EXPECTED_FIELDS:
            field_settings = card_fields.get(field_key, {})
            if field_key in processed_dict:
                final_extracted_fields[field_key] = {
                    **processed_dict[field_key],
                    "required": field_settings.get("required", False),  # Default to False
                    "enabled": field_settings.get("enabled", True)
                }
            else:
                print(f"ℹ️ Field '{field_key}' not found by Document AI, adding as blank.")
                final_extracted_fields[field_key] = {
                    "value": "",
                    "vision_confidence": 0.0,
                    "required": field_settings.get("required", False),  # Default to False
                    "enabled": field_settings.get("enabled", True),
                    "requires_human_review": field_settings.get("required", False),  # Mark for review if required
                    "review_notes": "Required field not found by Document AI" if field_settings.get("required", False) else "",
                    "source": "docai_missing"
                }
                # Special handling for city and state fields
                if field_key in ['city', 'state']:
                    final_extracted_fields[field_key].update({
                        "requires_human_review": True,  # Always require review for missing city/state
                        "review_notes": f"Required {field_key} field not found by Document AI"
                    })
        try:
            address = final_extracted_fields.get('address', {}).get('value', '')
            city = final_extracted_fields.get('city', {}).get('value', '')
            state = final_extracted_fields.get('state', {}).get('value', '')
            zip_code = final_extracted_fields.get('zip_code', {}).get('value', '')
            print("\n=== Pre-Validation Values ===")
            print(f"Address: '{address}'")
            print(f"City: '{city}'")
            print(f"State: '{state}'")
            print(f"Zip Code: '{zip_code}'")
            validation_result = validate_address_components(
                address=address,
                city=city,
                state=state,
                zip_code=zip_code
            )
            if validation_result:
                print("✅ Address validation completed")
                validated_data = validation_result['validated']
                # Always include city and state fields, using validated data if available
                final_extracted_fields['city'] = {
                    "value": validated_data['city'] if validated_data['city'] else city,
                    "vision_confidence": 0.95 if validated_data['city'] else 0.3,
                    "requires_human_review": not validated_data['city'],
                    "review_notes": "City not found in address validation" if not validated_data['city'] else "",
                    "source": "zip_validation" if validated_data['city'] else "original"
                }
                final_extracted_fields['state'] = {
                    "value": validated_data['state'] if validated_data['state'] else state,
                    "vision_confidence": 0.95 if validated_data['state'] else 0.3,
                    "requires_human_review": not validated_data['state'],
                    "review_notes": "State not found in address validation" if not validated_data['state'] else "",
                    "source": "zip_validation" if validated_data['state'] else "original"
                }
                # Always update zip code if validation provides one
                if validated_data['zip']:
                    final_extracted_fields['zip_code'] = {
                        "value": validated_data['zip'],
                        "vision_confidence": 0.95,
                        "requires_human_review": False,
                        "review_notes": "",
                        "source": "zip_validation"
                    }
                final_extracted_fields['address'] = {
                    "value": address if validation_result['requires_review'] else validated_data['street_address'],
                    "vision_confidence": validation_result['confidence'],
                    "requires_human_review": validation_result['requires_review'],
                    "review_notes": validation_result['review_notes'],
                    "suggested_value": validated_data['street_address'] if validation_result['requires_review'] and validated_data['street_address'] != address else None,
                    "source": "address_validation"
                }
            else:
                print("⚠️ Address validation failed completely")
                final_extracted_fields['address'] = {
                    "value": address,
                    "vision_confidence": 0.3,
                    "requires_human_review": True,
                    "review_notes": "Address validation failed",
                    "source": "validation_failed"
                }
        except Exception as val_error:
            print(f"⚠️ Error during address validation: {val_error}")
            final_extracted_fields['address'] = {
                "value": address,
                "vision_confidence": 0.3,
                "requires_human_review": True,
                "review_notes": f"Error validating address: {str(val_error)}",
                "source": "validation_error"
            }
        print(f"✅ Final extracted dictionary includes {len(final_extracted_fields)} fields (including added blanks).")
        return final_extracted_fields
    except Exception as e:
        print(f"❌ Error during process_image: {e}")
        traceback.print_exc()
        raise e

# --- Gemini Review ---
def get_gemini_review(all_fields: dict, image_path: str) -> dict:
    try:
        model = genai.GenerativeModel("gemini-1.5-pro-latest")
        model.generation_config = {
            "temperature": 0.1,
            "top_p": 0.8,
            "top_k": 40,
            "max_output_tokens": 2048,
        }
    except Exception as model_e:
        print(f"❌ Gemini model '{GEMINI_MODEL}' not accessible: {model_e}")
        print(f"❌ Gemini model 'gemini-1.5-pro-latest' not accessible: {model_e}")
        return {}
    try:
        prompt = GEMINI_PROMPT_TEMPLATE.format(
            all_fields_json=json.dumps(all_fields, indent=2)
        )
    except KeyError as e:
        print(f"❌ Error formatting prompt template: Missing '{{all_fields_json}}' placeholder in GEMINI_PROMPT_TEMPLATE. Check definition. Details: {e}")
        return {}
    except Exception as fmt_e:
        print(f"❌ Unexpected error formatting prompt template: {fmt_e}")
        traceback.print_exc()
        return {}
    response = None; cleaned_json_text = ""
    try:
        print(f"🧠 Sending request to Gemini for image: {os.path.basename(image_path)}")
        with io.open(image_path, "rb") as f: image_bytes = f.read()
        current_mime_type = mime_type
        image_part = {"mime_type": current_mime_type, "data": image_bytes}
        response = model.generate_content([prompt, image_part])
        print(f"🧠 Gemini Raw Response Text:\n{response.text}\n--------------------")
        cleaned_json_text = re.sub(r"```json\s*([\s\S]*?)\s*```", r"\1", response.text).strip()
        print(f"🧠 Attempting to parse JSON:\n{cleaned_json_text}\n--------------------")
        gemini_dict = json.loads(cleaned_json_text)
        
        # Preserve required flags and other metadata from original fields
        for field_name, field_data in gemini_dict.items():
            if field_name in all_fields:
                original_field = all_fields[field_name]
                if isinstance(field_data, dict):
                    field_data.update({
                        "required": original_field.get("required", False),
                        "enabled": original_field.get("enabled", True),
                        "confidence": original_field.get("confidence", 0.0),
                        "bounding_box": original_field.get("bounding_box", [])
                    })
        
        if isinstance(gemini_dict, dict): 
            print("✅ Gemini review successful, JSON parsed.")
            return gemini_dict
        else: 
            print(f"❌ Gemini response not a dictionary (type: {type(gemini_dict)}).")
            return {}
    except json.JSONDecodeError as json_e:
        print(f"❌ Error decoding Gemini JSON response: {json_e}")
        print(f"--- Faulty Text Start ---\n{cleaned_json_text[:1000]}\n--- Faulty Text End ---")
        traceback.print_exc()
        return {}
    except Exception as e:
        print(f"❌ Error in get_gemini_review (API call or other): {e}")
        if response:
            if hasattr(response, 'prompt_feedback'): print(f"Prompt Feedback: {response.prompt_feedback}")
            if hasattr(response, 'candidates') and response.candidates:
                 if hasattr(response.candidates[0], 'finish_reason'): print(f"Finish Reason: {response.candidates[0].finish_reason}")
                 if hasattr(response.candidates[0], 'safety_ratings'): print(f"Safety Ratings: {response.candidates[0].safety_ratings}")
        traceback.print_exc()
        return {}

# Gemini-only extraction
ALL_EXPECTED_FIELDS = [
    'name', 'preferred_first_name', 'date_of_birth', 'email', 'cell',
    'permission_to_text', 'address', 'city', 'state', 'zip_code',
    'high_school', 'class_rank', 'students_in_class', 'gpa',
    'student_type', 'entry_term', 'major', 'city_state'
]

def parse_card_with_gemini(image_path: str, docai_fields: Dict[str, Any], model_name: str = GEMINI_MODEL) -> Dict[str, Any]:
    max_retries = 3
    retry_delay = 2  # seconds
    timeout_seconds = 30
    genai.configure(api_key=os.getenv("GEMINI_API_KEY"))
    model = genai.GenerativeModel("gemini-1.5-pro-latest")
    
    # Clean field names by removing quotes
    cleaned_fields = {}
    for field_name, field_data in docai_fields.items():
        # Remove quotes from field name if present
        clean_name = field_name.strip('"')
        cleaned_fields[clean_name] = field_data
    
    # Debug logging for required flags
    print("[Gemini DEBUG] Checking required flags in DocAI fields:")
    for field_name, field_data in cleaned_fields.items():
        print(f"  {field_name}: required={field_data.get('required', False)}")
    
    print("[Gemini DEBUG] DocAI JSON being passed to Gemini:")
    print(json.dumps(cleaned_fields, indent=2))
    
    # Use the updated prompt template that includes required flags
    prompt = GEMINI_PROMPT_TEMPLATE.format(
        all_fields_json=json.dumps(cleaned_fields, indent=2)
    )
    
    response = None
    for attempt in range(max_retries):
        try:
            response = model.generate_content(prompt)
            if response and response.text:
                break
        except Exception as e:
            print(f"Attempt {attempt + 1} failed: {str(e)}")
            if attempt < max_retries - 1:
                time.sleep(retry_delay)
            else:
                raise e
    
    if not response or not response.text:
        raise Exception("Failed to get response from Gemini")
    
    try:
        # Clean the response text by removing markdown code block markers
        cleaned_text = response.text.strip()
        if cleaned_text.startswith("```json"):
            cleaned_text = cleaned_text[7:]  # Remove ```json
        if cleaned_text.endswith("```"):
            cleaned_text = cleaned_text[:-3]  # Remove ```
        cleaned_text = cleaned_text.strip()
        
        # Parse the cleaned response as JSON
        gemini_fields = json.loads(cleaned_text)
        
        # Ensure city and state fields exist
        if "city" not in gemini_fields:
            gemini_fields["city"] = {
                "value": "",
                "required": True,
                "enabled": True,
                "review_confidence": 0.0,
                "requires_human_review": True,
                "review_notes": "City field not found in response",
                "confidence": 0.0,
                "bounding_box": [],
                "source": "gemini_missing"
            }
        
        if "state" not in gemini_fields:
            gemini_fields["state"] = {
                "value": "",
                "required": True,
                "enabled": True,
                "review_confidence": 0.0,
                "requires_human_review": True,
                "review_notes": "State field not found in response",
                "confidence": 0.0,
                "bounding_box": [],
                "source": "gemini_missing"
            }
        
        # Handle city_state field by splitting it into city and state
        if "city_state" in gemini_fields:
            city_state_value = gemini_fields["city_state"]["value"]
            if city_state_value:
                # Split on comma and clean up
                parts = [part.strip() for part in city_state_value.split(",")]
                if len(parts) >= 2:
                    city = parts[0]
                    state = parts[1]
                    
                    # Create city field
                    gemini_fields["city"] = {
                        "value": city,
                        "required": True,
                        "enabled": True,
                        "review_confidence": gemini_fields["city_state"]["review_confidence"],
                        "requires_human_review": False,
                        "review_notes": "",
                        "confidence": gemini_fields["city_state"]["confidence"],
                        "bounding_box": gemini_fields["city_state"]["bounding_box"],
                        "source": "city_state_split"
                    }
                    
                    # Create state field
                    gemini_fields["state"] = {
                        "value": state,
                        "required": True,
                        "enabled": True,
                        "review_confidence": gemini_fields["city_state"]["review_confidence"],
                        "requires_human_review": False,
                        "review_notes": "",
                        "confidence": gemini_fields["city_state"]["confidence"],
                        "bounding_box": gemini_fields["city_state"]["bounding_box"],
                        "source": "city_state_split"
                    }
            
            # Remove the combined city_state field
            del gemini_fields["city_state"]
        
        # Preserve required flags and other metadata from DocAI fields
        for field_name, field_data in gemini_fields.items():
            if field_name in cleaned_fields:
                original_field = cleaned_fields[field_name]
                # Preserve all the original field metadata
                field_data.update({
                    "required": original_field.get("required", False),  # Default to False
                    "enabled": original_field.get("enabled", True),
                    "confidence": original_field.get("confidence", 0.0),
                    "bounding_box": original_field.get("bounding_box", [])
                })
                
                # If field is required and empty, mark for review
                if field_data.get("required", False) and not field_data.get("value"):
                    field_data["requires_human_review"] = True
                    field_data["review_notes"] = "Required field is empty"
                # If field is required and has low confidence, mark for review
                elif field_data.get("required", False) and field_data.get("confidence", 0.0) < 0.7:
                    field_data["requires_human_review"] = True
                    field_data["review_notes"] = "Required field has low confidence"
        
        print("[Gemini DEBUG] Processed fields with required flags:")
        print(json.dumps(gemini_fields, indent=2))
        
        return gemini_fields
    except json.JSONDecodeError as e:
        print(f"Failed to parse Gemini response as JSON: {str(e)}")
        print(f"Raw response: {response.text}")
        print(f"Cleaned text: {cleaned_text}")
        raise e 