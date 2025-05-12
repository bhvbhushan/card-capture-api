import os
import io
import json
import re
import traceback
from datetime import datetime, timezone
from fastapi.responses import JSONResponse
from app.core.clients import docai_client, docai_name, gmaps_client, mime_type
import googlemaps
import google.generativeai as genai
from typing import Dict, Any, Optional
from app.core.gemini_prompt import GEMINI_PROMPT_TEMPLATE

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
# def process_image(image_path: str) -> Dict[str, Any]:
#     if not docai_client or not docai_name:
#         raise ValueError("Document AI client not available")
#     print(f"🔍 Processing image '{os.path.basename(image_path)}' with Document AI...")
#     try:
#         with io.open(image_path, "rb") as image:
#             image_content = image.read()
#         current_mime_type = mime_type
#         from google.cloud import documentai_v1 as documentai
#         raw_document = documentai.RawDocument(content=image_content, mime_type=current_mime_type)
#         request = documentai.ProcessRequest(name=docai_name, raw_document=raw_document)
#         result = docai_client.process_document(request=request)
#         document = result.document
#         print(f"✅ Document AI OCR processing completed.")
#         print("-" * 20, "Document AI Raw Response Start", "-" * 20)
#         print("Detected Entities:")
#         if document.entities:
#             for entity in document.entities:
#                 print(f"  - Type: {entity.type_}\n    Mention Text: '{entity.mention_text}'\n    Confidence: {entity.confidence:.4f}")
#         else:
#             print("  No entities detected by the processor.")
#         print("-" * 20, "Document AI Raw Response End", "-" * 20)
#         processed_dict = {}
#         if document.entities:
#             for entity in document.entities:
#                 key = entity.type_
#                 value = entity.mention_text.strip()
#                 docai_confidence = entity.confidence
#                 processed_dict[key] = {"value": value, "vision_confidence": docai_confidence}
#             print(f"✅ Formatted {len(processed_dict)} fields found by Document AI.")
#         else:
#             print(f"⚠️ No entities found by Document AI.")
#         final_extracted_fields = {}
#         for field_key in ALL_EXPECTED_FIELDS:
#             if field_key in processed_dict:
#                 final_extracted_fields[field_key] = processed_dict[field_key]
#             else:
#                 print(f"ℹ️ Field '{field_key}' not found by Document AI, adding as blank.")
#                 final_extracted_fields[field_key] = {
#                     "value": "",
#                     "vision_confidence": 0.0
#                 }
#         try:
#             address = final_extracted_fields.get('address', {}).get('value', '')
#             city = final_extracted_fields.get('city', {}).get('value', '')
#             state = final_extracted_fields.get('state', {}).get('value', '')
#             zip_code = final_extracted_fields.get('zip_code', {}).get('value', '')
#             print("\n=== Pre-Validation Values ===")
#             print(f"Address: '{address}'")
#             print(f"City: '{city}'")
#             print(f"State: '{state}'")
#             print(f"Zip Code: '{zip_code}'")
#             validation_result = validate_address_components(
#                 address=address,
#                 city=city,
#                 state=state,
#                 zip_code=zip_code
#             )
#             if validation_result:
#                 print("✅ Address validation completed")
#                 validated_data = validation_result['validated']
#                 if validated_data['city']:
#                     final_extracted_fields['city'] = {
#                         "value": validated_data['city'],
#                         "vision_confidence": 0.95,
#                         "requires_human_review": False,
#                         "source": "zip_validation"
#                     }
#                 if validated_data['state']:
#                     final_extracted_fields['state'] = {
#                         "value": validated_data['state'],
#                         "vision_confidence": 0.95,
#                         "requires_human_review": False,
#                         "source": "zip_validation"
#                     }
#                 if validated_data['zip']:
#                     final_extracted_fields['zip_code'] = {
#                         "value": validated_data['zip'],
#                         "vision_confidence": 0.95,
#                         "requires_human_review": False,
#                         "source": "zip_validation"
#                     }
#                 final_extracted_fields['address'] = {
#                     "value": address if validation_result['requires_review'] else validated_data['street_address'],
#                     "vision_confidence": validation_result['confidence'],
#                     "requires_human_review": validation_result['requires_review'],
#                     "review_notes": validation_result['review_notes'],
#                     "suggested_value": validated_data['street_address'] if validation_result['requires_review'] and validated_data['street_address'] != address else None,
#                     "source": "address_validation"
#                 }
#             else:
#                 print("⚠️ Address validation failed completely")
#                 final_extracted_fields['address'] = {
#                     "value": address,
#                     "vision_confidence": 0.3,
#                     "requires_human_review": True,
#                     "review_notes": "Address validation failed",
#                     "source": "validation_failed"
#                 }
#         except Exception as val_error:
#             print(f"⚠️ Error during address validation: {val_error}")
#             final_extracted_fields['address'] = {
#                 "value": address,
#                 "vision_confidence": 0.3,
#                 "requires_human_review": True,
#                 "review_notes": f"Error validating address: {str(val_error)}",
#                 "source": "validation_error"
#             }
#         print(f"✅ Final extracted dictionary includes {len(final_extracted_fields)} fields (including added blanks).")
#         return final_extracted_fields
#     except Exception as e:
#         print(f"❌ Error during process_image: {e}")
#         traceback.print_exc()
#         raise e

# --- Gemini Review ---
def get_gemini_review(all_fields: dict, image_path: str) -> dict:
    try:
        model = genai.GenerativeModel("models/gemini-2.5-pro-preview-03-25")
    except Exception as model_e:
        print(f"❌ Gemini model 'gemini-2.5-pro-preview-03-25' not accessible: {model_e}")
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
        if isinstance(gemini_dict, dict): print("✅ Gemini review successful, JSON parsed."); return gemini_dict
        else: print(f"❌ Gemini response not a dictionary (type: {type(gemini_dict)})."); return {}
    except json.JSONDecodeError as json_e:
        print(f"❌ Error decoding Gemini JSON response: {json_e}")
        print(f"--- Faulty Text Start ---\n{cleaned_json_text[:1000]}\n--- Faulty Text End ---")
        traceback.print_exc(); return {}
    except Exception as e:
        print(f"❌ Error in get_gemini_review (API call or other): {e}")
        if response:
            if hasattr(response, 'prompt_feedback'): print(f"Prompt Feedback: {response.prompt_feedback}")
            if hasattr(response, 'candidates') and response.candidates:
                 if hasattr(response.candidates[0], 'finish_reason'): print(f"Finish Reason: {response.candidates[0].finish_reason}")
                 if hasattr(response.candidates[0], 'safety_ratings'): print(f"Safety Ratings: {response.candidates[0].safety_ratings}")
        traceback.print_exc(); return {}

# Gemini-only extraction
ALL_EXPECTED_FIELDS = [
    'name', 'preferred_first_name', 'date_of_birth', 'email', 'cell',
    'permission_to_text', 'address', 'city', 'state', 'zip_code',
    'high_school', 'class_rank', 'students_in_class', 'gpa',
    'student_type', 'entry_term', 'major', 'city_state'
]

def parse_card_with_gemini(image_path: str, model_name: str = "gemini-2.5-pro-preview-03-25") -> Dict[str, Any]:
    fields_list = "\n".join([
        f'    "{field}": {{ "value": "", "confidence": 0.0, "requires_human_review": false, "review_notes": "" }},' for field in ALL_EXPECTED_FIELDS
    ])
    prompt = f"""
You are an expert at extracting information from student contact cards.\nAnalyze this card image and extract all relevant information.\n\nReturn the data in the following JSON format without any markdown formatting or additional text:\n{{\n{fields_list}\n}}\n\nImportant:\n- Include ALL of the above fields in the output, even if the value is missing (set value to "" and confidence to 0.0).\n- For each field, use this structure:\n  {{\n    \"value\": \"extracted value or empty string\",\n    \"confidence\": 0.95,\n    \"requires_human_review\": false,\n    \"review_notes\": \"any notes about potential issues\"\n  }}\n- If a field is unclear or potentially incorrect, set requires_human_review to true.\n- If you're very confident (>0.9), add a note explaining why.\n- If you see any special cases or formatting issues, mention them in review_notes.\n- Keep the original formatting/capitalization of values.\n- Return ONLY the JSON with no additional text, explanation, or markdown formatting.\n"""
    try:
        genai.configure(api_key=os.getenv("GEMINI_API_KEY"))
        model = genai.GenerativeModel(model_name)
        with open(image_path, "rb") as image_file:
            image_bytes = image_file.read()
        mime_type = "image/jpeg" if image_path.lower().endswith((".jpg", ".jpeg")) else "image/png"
        image_part = {"mime_type": mime_type, "data": image_bytes}
        print(f"🧠 Sending request to Gemini using model: {model_name}...")
        response = model.generate_content([prompt, image_part])
        print("\n🔍 Raw Gemini Response:")
        print("-" * 50)
        print(response.text)
        print("-" * 50)
        cleaned_text = response.text.replace("```json", "").replace("```", "").strip()
        parsed_data = json.loads(cleaned_text)
        # Ensure all expected fields are present
        for field in ALL_EXPECTED_FIELDS:
            if field not in parsed_data:
                parsed_data[field] = {"value": "", "confidence": 0.0, "requires_human_review": False, "review_notes": ""}
        print("\n✅ Successfully parsed card data:")
        print(json.dumps(parsed_data, indent=2))
        return parsed_data
    except Exception as e:
        print(f"\n❌ Error parsing card: {str(e)}")
        import traceback
        traceback.print_exc()
        # Return all fields blank if error
        return {field: {"value": "", "confidence": 0.0, "requires_human_review": False, "review_notes": ""} for field in ALL_EXPECTED_FIELDS} 