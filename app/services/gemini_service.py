from datetime import datetime, timezone
import os
from app.core.clients import supabase_client
from app.repositories.reviewed_data_repository import upsert_reviewed_data
from app.repositories.extracted_data_repository import get_extracted_data_by_document_id
from app.repositories.upload_notifications_repository import insert_upload_notification
import traceback
import json
import re
import time
from typing import Dict, Any, Tuple, Callable
import google.generativeai as genai
from app.core.gemini_prompt import GEMINI_PROMPT_TEMPLATE
from app.config import GEMINI_MODEL
from app.utils.retry_utils import retry_with_exponential_backoff, log_debug

def process_card_with_gemini_v2(image_path: str, docai_fields: Dict[str, Any], valid_majors: list = None) -> Dict[str, Any]:
    """
    Enhanced Gemini processing that uses quality indicators instead of confidence self-assessment
    
    Args:
        image_path: Path to the cropped image
        docai_fields: Fields from DocAI with requirements applied
        valid_majors: List of valid majors for mapped_major logic
        
    Returns:
        Enhanced field data with computed confidence scores
    """
    log_debug("=== GEMINI PROCESSING V2 START ===", service="gemini")
    log_debug(f"Image path: {image_path}", service="gemini")
    log_debug("Input DocAI fields", {
        field_name: {
            "value": field_data.get("value", ""),
            "required": field_data.get("required", False),
            "enabled": field_data.get("enabled", True)
        }
        for field_name, field_data in docai_fields.items()
    }, service="gemini")
    
    if valid_majors is None:
        valid_majors = []
    try:
        # Configure Gemini
        genai.configure(api_key=os.getenv("GEMINI_API_KEY"))
        model = genai.GenerativeModel("gemini-1.5-pro-latest")
        
        # Prepare input for Gemini (fields + valid_majors)
        gemini_input = {
            "fields": {
                field_name: {
                    "value": field_data.get("value", ""),
                    "confidence": field_data.get("confidence", 0.0),
                    "required": field_data.get("required", False),
                    "enabled": field_data.get("enabled", True)
                }
                for field_name, field_data in docai_fields.items() if field_data.get("enabled", True)
            },
            "valid_majors": valid_majors
        }
        
        log_debug("Gemini input prepared", gemini_input, service="gemini")
        
        # Create prompt
        prompt = GEMINI_PROMPT_TEMPLATE.format(
            all_fields_json=json.dumps(gemini_input["fields"], indent=2),
            list_of_valid_majors=json.dumps(valid_majors, indent=2)
        )
        
        # Upload image with retry logic
        log_debug("Uploading image to Gemini...", service="gemini")
        uploaded_file = retry_with_exponential_backoff(
            func=lambda: genai.upload_file(image_path),
            max_retries=3,
            operation_name="Gemini image upload",
            service="gemini"
        )
        
        log_debug("Sending request to Gemini...", service="gemini")
        log_debug("Prompt being sent:", prompt, service="gemini")
        
        # Generate content with retry logic
        response = retry_with_exponential_backoff(
            func=lambda: model.generate_content([uploaded_file, prompt]),
            max_retries=3,
            operation_name="Gemini content generation",
            service="gemini"
        )
        
        if not response or not response.text:
            raise Exception("No response from Gemini")
        
        log_debug("Raw Gemini response", response.text, service="gemini")
        
        # Parse response with quality indicators
        try:
            enhanced_fields = parse_gemini_quality_response(response.text, docai_fields)
            # Backend safeguard: ensure mapped_major is always present
            if 'mapped_major' not in enhanced_fields:
                enhanced_fields['mapped_major'] = {
                    "value": "",
                    "edit_made": False,
                    "edit_type": "mapped_value",
                    "original_value": "",
                    "text_clarity": "clear",
                    "certainty": "certain",
                    "notes": ""
                }
            # Backend safeguard: ensure major is user's input, not mapped value
            if 'major' in enhanced_fields and 'mapped_major' in enhanced_fields and valid_majors:
                user_major_original = docai_fields.get('major', {}).get('value', '').strip().lower()
                gemini_major = enhanced_fields['major'].get('value', '').strip().lower()
                mapped_major = enhanced_fields['mapped_major'].get('value', '').strip().lower()
                # If Gemini set major to a mapped value, but user input was different, restore user input
                if mapped_major and gemini_major == mapped_major and user_major_original and user_major_original != mapped_major:
                    enhanced_fields['major']['value'] = docai_fields['major']['value']
        except json.JSONDecodeError as e:
            log_debug(f"JSON parsing error: {str(e)}", service="gemini")
            log_debug("Failed to parse response as JSON. Response text:", response.text, service="gemini")
            raise Exception(f"Invalid JSON response from Gemini: {str(e)}")
        except Exception as e:
            log_debug(f"Error parsing Gemini response: {str(e)}", service="gemini")
            log_debug("Response that caused error:", response.text, service="gemini")
            raise
        
        log_debug("Enhanced fields created", {
            field_name: {
                "value": field_data.get("value", ""),
                "confidence_score": field_data.get("review_confidence", 0.0),
                "requires_review": field_data.get("requires_human_review", False),
                "review_notes": field_data.get("review_notes", "")
            }
            for field_name, field_data in enhanced_fields.items()
        }, service="gemini")
        
        log_debug("=== GEMINI PROCESSING V2 COMPLETE ===", service="gemini")
        return enhanced_fields
        
    except Exception as e:
        log_debug(f"ERROR in Gemini processing: {str(e)}", service="gemini")
        log_debug("Full traceback:", traceback.format_exc(), service="gemini")
        # Return original fields with error flags
        for field_name, field_data in docai_fields.items():
            field_data["requires_human_review"] = True
            field_data["review_notes"] = "This field needs manual review due to a processing issue"
            field_data["review_confidence"] = 0.1
        return docai_fields

def parse_gemini_quality_response(response_text: str, docai_fields: Dict[str, Any]) -> Dict[str, Any]:
    """
    Parse Gemini response with quality indicators and convert to confidence scores
    
    Args:
        response_text: Raw Gemini response with quality indicators
        docai_fields: Original DocAI fields for metadata preservation
        
    Returns:
        Enhanced field data with computed confidence scores
    """
    log_debug("=== PARSING GEMINI QUALITY RESPONSE ===", service="gemini")
    
    try:
        # Clean response text
        cleaned_text = response_text.strip()
        
        # Remove markdown code block markers if present
        if cleaned_text.startswith("```json"):
            cleaned_text = cleaned_text[7:]
        elif cleaned_text.startswith("```"):
            cleaned_text = cleaned_text[3:]
        if cleaned_text.endswith("```"):
            cleaned_text = cleaned_text[:-3]
        cleaned_text = cleaned_text.strip()
        
        log_debug("Cleaned response text", cleaned_text, service="gemini")
        
        # Try to parse JSON
        try:
            gemini_data = json.loads(cleaned_text)
        except json.JSONDecodeError as e:
            log_debug(f"Initial JSON parse failed: {str(e)}", service="gemini")
            # Try to fix common JSON issues
            cleaned_text = cleaned_text.replace("'", '"')  # Replace single quotes with double quotes
            cleaned_text = re.sub(r'(\w+):', r'"\1":', cleaned_text)  # Quote unquoted keys
            log_debug("Attempting to parse with fixes", cleaned_text, service="gemini")
            gemini_data = json.loads(cleaned_text)
        
        log_debug("Parsed Gemini data", gemini_data, service="gemini")
        
        enhanced_fields = {}
        
        for field_name, quality_info in gemini_data.items():
            # Start with DocAI field data if it exists
            if field_name in docai_fields:
                enhanced_field = docai_fields[field_name].copy()
            else:
                # Create new field for data not detected by DocAI
                enhanced_field = {
                    "value": "",
                    "confidence": 0.0,
                    "bounding_box": [],
                    "source": "docai",
                    "enabled": True,
                    "required": False,
                    "requires_human_review": False,
                    "review_notes": "",
                    "review_confidence": 0.0
                }
            
            # Update with Gemini data
            enhanced_field["value"] = quality_info.get("value", "")
            enhanced_field["source"] = "gemini"
            
            # Convert quality indicators to confidence score
            confidence_score = calculate_confidence_from_quality(quality_info)
            enhanced_field["review_confidence"] = confidence_score
            
            # Determine if field needs review
            needs_review, review_notes = determine_review_from_quality(
                quality_info, enhanced_field
            )
            enhanced_field["requires_human_review"] = needs_review
            if review_notes:
                enhanced_field["review_notes"] = review_notes
            
            # Store quality metadata for debugging
            enhanced_field["quality_metadata"] = {
                "edit_made": quality_info.get("edit_made", False),
                "edit_type": quality_info.get("edit_type", "none"),
                "original_value": quality_info.get("original_value", ""),
                "text_clarity": quality_info.get("text_clarity", "unclear"),
                "certainty": quality_info.get("certainty", "uncertain"),
                "notes": quality_info.get("notes", "")
            }
            
            enhanced_fields[field_name] = enhanced_field
            
            log_debug(f"Enhanced field {field_name}", {
                "value": enhanced_field["value"],
                "confidence": confidence_score,
                "needs_review": needs_review,
                "review_notes": review_notes
            }, service="gemini")
        
        return enhanced_fields
        
    except Exception as e:
        log_debug(f"ERROR parsing Gemini response: {str(e)}", service="gemini")
        log_debug("Response text that caused error:", response_text, service="gemini")
        raise

def calculate_confidence_from_quality(quality_info: Dict[str, Any]) -> float:
    """
    Convert Gemini quality indicators to a reliable confidence score
    
    Args:
        quality_info: Quality indicators from Gemini
        
    Returns:
        Confidence score between 0.0 and 1.0
    """
    text_clarity = quality_info.get("text_clarity", "unclear")
    certainty = quality_info.get("certainty", "uncertain")
    edit_type = quality_info.get("edit_type", "none")
    value = quality_info.get("value", "")
    
    # Base confidence from text clarity
    clarity_scores = {
        "clear": 0.95,
        "mostly_clear": 0.85,
        "unclear": 0.40,
        "unreadable": 0.10
    }
    
    # Certainty modifiers
    certainty_modifiers = {
        "certain": 1.0,
        "mostly_certain": 0.9,
        "uncertain": 0.5
    }
    
    # Edit type modifiers - updated to be more generous for obvious corrections
    edit_modifiers = {
        "format_correction": 1.0,        # High confidence for obvious fixes
        "ocr_correction": 0.95,          # Good confidence for clear OCR fixes
        "typo_fix": 0.95,               # High confidence for obvious typo fixes (was 0.9)
        "cross_validation_fix": 1.0,     # High confidence for fixes based on other fields
        "missing_data": 0.75,            # Medium confidence for new data
        "unclear_text": 0.3,            # Low confidence for unclear text
        "none": 1.0                      # No penalty for no edits
    }
    
    # Calculate base score
    base_score = clarity_scores.get(text_clarity, 0.5)
    certainty_mod = certainty_modifiers.get(certainty, 0.5)
    edit_mod = edit_modifiers.get(edit_type, 0.5)
    
    # Empty values get low confidence
    if not value or value.strip() == "":
        return 0.1
    
    # Special boost for obvious corrections with good text clarity
    # If it's a typo_fix or format_correction with mostly_clear+ text, boost confidence
    if edit_type in ["typo_fix", "format_correction", "cross_validation_fix"] and text_clarity in ["clear", "mostly_clear"]:
        # For obvious corrections, treat "mostly_certain" as "certain"
        if certainty == "mostly_certain":
            certainty_mod = 1.0
    
    # Calculate final score
    final_score = base_score * certainty_mod * edit_mod
    
    # Ensure score is between 0.0 and 1.0
    return min(max(final_score, 0.0), 1.0)

def determine_review_from_quality(quality_info: Dict[str, Any], field_data: Dict[str, Any]) -> Tuple[bool, str]:
    """
    Determine if field needs human review based on quality indicators
    
    Args:
        quality_info: Quality indicators from Gemini
        field_data: Enhanced field data with requirements
        
    Returns:
        Tuple of (needs_review: bool, review_notes: str)
    """
    value = quality_info.get("value", "")
    certainty = quality_info.get("certainty", "uncertain")
    text_clarity = quality_info.get("text_clarity", "unclear")
    edit_type = quality_info.get("edit_type", "none")
    is_required = field_data.get("required", False)
    gemini_notes = quality_info.get("notes", "")
    confidence_score = calculate_confidence_from_quality(quality_info)
    
    # Always review if marked as uncertain
    if certainty == "uncertain":
        if gemini_notes:
            return True, gemini_notes
        return True, "This field needs a closer look - the text wasn't clear enough to read confidently"
    
    # Always review unreadable text
    if text_clarity == "unreadable":
        if gemini_notes:
            return True, gemini_notes
        return True, "The text here is too unclear to read"
    
    # Always review unclear text edits
    if edit_type == "unclear_text":
        if gemini_notes:
            return True, gemini_notes
        return True, "The handwriting here is difficult to make out clearly"
    
    # Review required fields that are empty
    if is_required and (not value or value.strip() == ""):
        if gemini_notes:
            return True, gemini_notes
        return True, "This required field appears to be empty"
    
    # Review required fields with low confidence
    if is_required and confidence_score < 0.7:
        if gemini_notes:
            return True, gemini_notes
        return True, "This required field could use a second look to make sure it's accurate"
    
    # Review if Gemini notes indicate uncertainty (check for uncertainty keywords)
    if gemini_notes and any(word in gemini_notes.lower() for word in ["unclear", "unsure", "hard to", "difficult", "might", "could be", "ambiguous", "faded", "messy"]):
        return True, gemini_notes
    
    # Field looks good
    return False, "" 