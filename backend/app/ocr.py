from PIL import Image, ImageOps
import pytesseract

# ponytail: gray + autocontrast + 4x upscale for small photos — measured better
# printed-text accuracy. Cursive handwriting is beyond Tesseract entirely;
# the upgrade path is a vision-LLM OCR pass (fits the future agent architecture),
# not a heavier local dependency stack.
_UPSCALE_IF_SMALLER_THAN = 1200  # px; guards memory on big scans


def extract_text(file_path: str) -> str:
    with Image.open(file_path) as src:
        image = ImageOps.autocontrast(ImageOps.grayscale(src))
        if max(image.size) < _UPSCALE_IF_SMALLER_THAN:
            image = image.resize((image.width * 4, image.height * 4))
        return pytesseract.image_to_string(image).strip()
