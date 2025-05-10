import os
from trim_card import trim_card

def ensure_trimmed_image(original_image_path: str) -> str:
    print(f"🔄 Processing image: {original_image_path}")
    try:
        trimmed_path = trim_card(original_image_path, original_image_path, pad=20)
        if not os.path.exists(trimmed_path):
            print(f"⚠️ Trimmed image not found at: {trimmed_path}")
            return original_image_path
        print(f"✅ Image processed and saved at: {trimmed_path}")
        return trimmed_path
    except Exception as e:
        print(f"❌ Error processing image: {e}")
        return original_image_path 