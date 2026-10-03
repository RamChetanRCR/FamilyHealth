from PIL import Image
import pytesseract


def extract_text(file_path: str) -> str:
    image = Image.open(file_path)
    return pytesseract.image_to_string(image).strip()
