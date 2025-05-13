import os
from pdf2image import convert_from_path

def split_pdf_to_pngs(pdf_path, output_dir):
    """
    Splits a PDF into individual PNG images, one per page.
    Args:
        pdf_path (str): Path to the PDF file.
        output_dir (str): Directory to save PNG images.
    Returns:
        List[str]: List of file paths to the generated PNG images.
    """
    try:
        images = convert_from_path(pdf_path)
        png_paths = []
        for i, image in enumerate(images):
            png_path = os.path.join(output_dir, f"page_{i+1}.png")
            image.save(png_path, 'PNG')
            png_paths.append(png_path)
        return png_paths
    except Exception as e:
        print(f"❌ Error splitting PDF {pdf_path}: {e}")
        return []