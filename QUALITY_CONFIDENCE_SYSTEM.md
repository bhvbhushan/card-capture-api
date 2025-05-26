# Quality-Based Confidence System

## Overview

The new quality-based confidence system replaces unreliable AI self-assessment with objective quality indicators that are converted to confidence scores using clear business rules.

## Key Benefits

✅ **Reliable**: Based on objective quality indicators, not AI self-assessment  
✅ **Simple**: Clear business rules that are easy to understand  
✅ **Consistent**: Same logic applied every time  
✅ **Debuggable**: Clear reasons for review flags  
✅ **Fail-safe**: When in doubt, flags for human review rather than letting bad data through  

## How It Works

### 1. Quality Indicators from Gemini

Instead of asking Gemini for confidence scores, we ask for quality indicators:

```json
{
  "field_name": {
    "value": "john@gmail.com",
    "edit_made": true,
    "edit_type": "format_correction",
    "original_value": "john@gmai.com", 
    "text_clarity": "clear",
    "certainty": "certain",
    "notes": "Fixed obvious typo: gmai → gmail"
  }
}
```

### 2. Quality Indicator Definitions

**edit_made**: Did you change the original value?
- `true`: Modified the original DocAI value
- `false`: Kept the original value unchanged

**edit_type**: What kind of edit did you make?
- `none`: No changes made
- `format_correction`: Fixed obvious formatting (email typos, phone format, etc.)
- `ocr_correction`: Fixed clear OCR errors (0→O, 1→I, etc.)
- `missing_data`: Added data not detected by DocAI
- `unclear_text`: Text exists but too unclear to read confidently
- `typo_fix`: Fixed obvious spelling/typing errors

**text_clarity**: How clear was the original text on the image?
- `clear`: Text is perfectly readable
- `mostly_clear`: Text is readable with minor issues
- `unclear`: Text is hard to read but partially interpretable
- `unreadable`: Text is too unclear/messy to read reliably

**certainty**: How certain are you about your final value?
- `certain`: You are confident this value is correct
- `mostly_certain`: You are reasonably confident but some doubt
- `uncertain`: You are not confident about this value

### 3. Confidence Score Calculation

Business rules convert quality indicators to confidence scores:

```python
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

# Edit type modifiers
edit_modifiers = {
    "format_correction": 1.0,    # High confidence for obvious fixes
    "ocr_correction": 0.95,      # Good confidence for clear OCR fixes
    "typo_fix": 0.9,            # Good confidence for typo fixes
    "missing_data": 0.75,        # Medium confidence for new data
    "unclear_text": 0.3,        # Low confidence for unclear text
    "none": 1.0                  # No penalty for no edits
}

final_score = base_score * certainty_mod * edit_mod
```

### 4. Review Determination

Clear business rules determine when fields need human review:

- **Always review if marked as uncertain**
- **Always review unreadable text**
- **Always review unclear text edits**
- **Review required fields that are empty**
- **Review required fields with low confidence (< 0.7)**
- **Review if Gemini notes indicate uncertainty**

## Example Scenarios

### ✅ High Confidence - No Review Needed
```json
{
  "email": {
    "value": "john@gmail.com",
    "edit_made": true,
    "edit_type": "format_correction",
    "text_clarity": "clear",
    "certainty": "certain",
    "notes": "Fixed obvious typo: gmai → gmail"
  }
}
```
**Result**: Confidence 0.95, No review needed

### ⚠️ Low Confidence - Review Required
```json
{
  "name": {
    "value": "",
    "edit_made": false,
    "edit_type": "unclear_text",
    "text_clarity": "unreadable",
    "certainty": "uncertain",
    "notes": "Handwriting too messy to read reliably"
  }
}
```
**Result**: Confidence 0.10, Review required: "Gemini marked as uncertain"

## Implementation Files

- **`app/core/gemini_prompt.py`**: Enhanced prompt with quality indicators
- **`app/services/gemini_service.py`**: Quality parsing and confidence calculation
- **`app/worker/worker_v2.py`**: Updated to use new Gemini service
- **`test_quality_confidence.py`**: Comprehensive test suite

## Test Results

All test scenarios pass:
- ✅ Clear email fixes get high confidence (> 0.9)
- ✅ Unclear handwriting gets flagged for review
- ✅ Missing required fields get flagged for review
- ✅ Good OCR corrections get high confidence (> 0.8)
- ✅ Uncertain fields get flagged for review
- ✅ Optional empty fields don't get flagged
- ✅ Edge cases handled gracefully

## Migration Notes

The new system is backward compatible:
- Existing field structure preserved
- Same confidence score range (0.0 - 1.0)
- Same review flagging mechanism
- Enhanced with quality metadata for debugging

## Debugging

Quality metadata is stored for each field:
```json
{
  "quality_metadata": {
    "edit_made": true,
    "edit_type": "format_correction",
    "original_value": "john@gmai.com",
    "text_clarity": "clear",
    "certainty": "certain",
    "notes": "Fixed obvious typo: gmai → gmail"
  }
}
```

This provides complete audit trail of why confidence scores were assigned and why fields were flagged for review. 