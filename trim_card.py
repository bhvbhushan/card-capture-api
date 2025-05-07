#!/usr/bin/env python3
import os
import cv2
import numpy as np

def trim_card(input_path, output_path, pad: int = 0, debug_dir: str = None):
    """
    Detects and trims a card from an image using thresholding and contour detection.
    
    Args:
        input_path: Path to the input image
        output_path: Path to save the output image (if None, overwrites input)
        pad: Number of pixels to pad around the detected card
        debug_dir: Directory to save debug images (if None, no debug images are saved)
    
    Returns:
        Path where the trimmed image was saved
    """
    # --- 1. load
    img = cv2.imread(input_path)
    if img is None:
        raise FileNotFoundError(f"Could not read '{input_path}'")
    orig = img.copy()
    h, w = img.shape[:2]

    # --- 2. mask out the white border by thresholding "near-white"
    gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)
    # any pixel >245 (on 0–255) is background
    _, mask = cv2.threshold(gray, 245, 255, cv2.THRESH_BINARY_INV)

    # --- 3. clean it up
    kernel = np.ones((5,5), np.uint8)
    mask = cv2.morphologyEx(mask, cv2.MORPH_CLOSE, kernel, iterations=2)
    mask = cv2.morphologyEx(mask, cv2.MORPH_OPEN,  kernel, iterations=2)

    # optional debug
    if debug_dir:
        os.makedirs(debug_dir, exist_ok=True)
        cv2.imwrite(os.path.join(debug_dir, "mask.png"), mask)

    # --- 4. find the biggest blob
    contours, _ = cv2.findContours(mask, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
    if not contours:
        # nothing found, just dump the original
        cv2.imwrite(output_path, orig)
        return output_path

    # pick the largest area contour
    c = max(contours, key=cv2.contourArea)
    x,y,wc,hc = cv2.boundingRect(c)

    # optional debug
    if debug_dir:
        dbg = orig.copy()
        cv2.rectangle(dbg, (x,y), (x+wc, y+hc), (0,255,0), 3)
        cv2.imwrite(os.path.join(debug_dir, "bbox.png"), dbg)

    # --- 5. apply padding and crop
    x1 = max(0, x - pad)
    y1 = max(0, y - pad)
    x2 = min(orig.shape[1], x + wc + pad)
    y2 = min(orig.shape[0], y + hc + pad)
    cropped = orig[y1:y2, x1:x2]

    # Apply 40% zoom by resizing
    height, width = cropped.shape[:2]
    zoomed = cv2.resize(cropped, (int(width * 1.4), int(height * 1.4)), 
                       interpolation=cv2.INTER_LINEAR)

    # final write
    cv2.imwrite(output_path, zoomed)
    return output_path

def test_card_detection():
    # Create debug output directory in root
    root_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    debug_dir = os.path.join(root_dir, 'debug_output')
    os.makedirs(debug_dir, exist_ok=True)
    
    # Test image path - using page_33.png
    test_image_path = os.path.join(root_dir, 'test_images', 'page_33.png')
    
    if not os.path.exists(test_image_path):
        print(f"Test image not found at {test_image_path}")
        return
        
    # Process image and save debug output
    output_path = os.path.join(debug_dir, 'trimmed_output.png')
    debug_base = os.path.join(debug_dir, 'trimmed_output')
    
    print(f"Processing image: {test_image_path}")
    print(f"Saving output to: {output_path}")
    
    # Call trim_card with debug output path
    result = trim_card(test_image_path, output_path, add_border=20)
    
    # List all debug files
    print("\nDebug files generated in debug_output directory:")
    for file in os.listdir(debug_dir):
        print(f"- {file}")

if __name__ == "__main__":
    import argparse
    p = argparse.ArgumentParser(description="Trim a card scan to its colored interior")
    p.add_argument("input", help="input image file")
    p.add_argument("output", help="output (cropped) file")
    p.add_argument("--pad",   type=int, default=0, help="pixels of padding inside the crop")
    p.add_argument("--debug", help="directory to dump intermediate mask/bbox images")
    args = p.parse_args()

    # ensure debug dir exists
    debug_dir = args.debug or None

    trim_card(args.input, args.output, pad=args.pad, debug_dir=debug_dir)
    print("✅ Done cropping.") 