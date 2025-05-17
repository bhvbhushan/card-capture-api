#!/usr/bin/env python3
import os
import io
import json
import google.generativeai as genai
from dotenv import load_dotenv
from typing import Dict, Any, Optional

# Load environment variables
load_dotenv()
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY")

# Configure Gemini
genai.configure(api_key=GEMINI_API_KEY)

# Prompt template for direct card parsing
GEMINI_DIRECT_PROMPT = """You are an expert at extracting information from student contact cards. 
Analyze this card image and extract all relevant information.

Return the data in the following JSON format without any markdown formatting or additional text:
{
    "name": {
        "value": "extracted name",
        "confidence": 0.95,
        "requires_human_review": false,
        "review_notes": "any notes about potential issues"
    },
    "address": { ... },
    "city_state": { ... },
    "zip_code": { ... },
    "phone": { ... },
    "email": { ... },
    "preferred_name": { ... }
}

Important:
- If a field is unclear or potentially incorrect, set requires_human_review to true
- If you're very confident (>0.9), add a note explaining why
- If you see any special cases or formatting issues, mention them in review_notes
- Keep the original formatting/capitalization of values
- Return ONLY the JSON with no additional text, explanation, or markdown formatting
"""

def parse_card_with_gemini(image_path: str, model_name: str = " gemini-1.5-pro-latest") -> Optional[Dict[str, Any]]:
    """
    Parse a card image directly with Gemini, bypassing Document AI.
    
    Args:
        image_path: Path to the card image
        model_name: Gemini model to use
        
    Returns:
        Dictionary containing the extracted fields and metadata, or None if parsing failed
    """
    try:
        print(f"🔍 Processing image: {os.path.basename(image_path)}")
        
        # Initialize Gemini model
        model = genai.GenerativeModel(model_name)
        
        # Read image
        with open(image_path, "rb") as image_file:
            image_bytes = image_file.read()
        
        # Determine mime type (you might want to make this more sophisticated)
        mime_type = "image/jpeg" if image_path.lower().endswith(('.jpg', '.jpeg')) else "image/png"
        
        # Create image part
        image_part = {"mime_type": mime_type, "data": image_bytes}
        
        # Generate content
        print(f"🧠 Sending request to Gemini using model: {model_name}...")
        response = model.generate_content([GEMINI_DIRECT_PROMPT, image_part])
        
        # Log raw response for debugging
        print("\n🔍 Raw Gemini Response:")
        print("-" * 50)
        print(response.text)
        print("-" * 50)
        
        # Clean and parse the response
        # Remove markdown code blocks if present
        cleaned_text = response.text.replace("```json", "").replace("```", "").strip()
        
        # Parse JSON
        parsed_data = json.loads(cleaned_text)
        
        # Validate the response format
        if not isinstance(parsed_data, dict):
            raise ValueError("Gemini response is not a dictionary")
            
        print("\n✅ Successfully parsed card data:")
        print(json.dumps(parsed_data, indent=2))
        
        return parsed_data
        
    except Exception as e:
        print(f"\n❌ Error parsing card: {str(e)}")
        import traceback
        traceback.print_exc()
        return None

def compare_with_docai_results(gemini_results: Dict[str, Any], docai_file: str) -> None:
    """
    Compare Gemini's results with saved Document AI results.
    
    Args:
        gemini_results: Results from Gemini parsing
        docai_file: Path to JSON file containing Document AI results
    """
    try:
        with open(docai_file, 'r') as f:
            docai_results = json.load(f)
            
        print("\n📊 Comparison with Document AI results:")
        print("-" * 50)
        
        all_fields = set(gemini_results.keys()) | set(docai_results.keys())
        
        for field in sorted(all_fields):
            gemini_value = gemini_results.get(field, {}).get('value', 'N/A')
            docai_value = docai_results.get(field, {}).get('value', 'N/A')
            
            print(f"\nField: {field}")
            print(f"  Gemini: {gemini_value}")
            print(f"  DocAI:  {docai_value}")
            
            if gemini_value != docai_value and gemini_value != 'N/A' and docai_value != 'N/A':
                print(f"  ⚠️  Values differ!")
                print(f"  Gemini confidence: {gemini_results[field].get('confidence', 'N/A')}")
                print(f"  Gemini review notes: {gemini_results[field].get('review_notes', 'N/A')}")
                
    except FileNotFoundError:
        print(f"\n⚠️  Document AI results file not found: {docai_file}")
    except Exception as e:
        print(f"\n❌ Error comparing results: {str(e)}")

def main():
    import argparse
    parser = argparse.ArgumentParser(description="Parse card images using Gemini AI directly")
    parser.add_argument("image_path", help="Path to the card image to parse")
    parser.add_argument("--compare", help="Path to JSON file with Document AI results to compare with", default=None)
    parser.add_argument("--output", help="Path to save Gemini results as JSON", default=None)
    parser.add_argument("--model", help="Gemini model to use", default=" gemini-1.5-pro-latest")
    
    args = parser.parse_args()
    
    # Parse the card
    results = parse_card_with_gemini(args.image_path, args.model)
    
    # Save results if requested
    if args.output and results:
        os.makedirs(os.path.dirname(args.output) or '.', exist_ok=True)
        with open(args.output, 'w') as f:
            json.dump(results, f, indent=2)
        print(f"\n💾 Results saved to: {args.output}")
    
    # Compare with Document AI results if provided
    if args.compare and results:
        compare_with_docai_results(results, args.compare)

if __name__ == "__main__":
    main() 