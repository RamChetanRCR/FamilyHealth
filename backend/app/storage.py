import os

from pathlib import Path
import shutil
from uuid import uuid4

from PIL import Image

STORAGE_DIR = Path(os.getenv("STORAGE_DIR", "/data/documents"))

_IMAGE_FORMAT = {"image/jpeg": "JPEG", "image/png": "PNG"}


def save_document(file):
    STORAGE_DIR.mkdir(parents=True, exist_ok=True)

    extension = Path(file.filename or "").suffix.lower()
    filename = f"{uuid4().hex}{extension}"
    destination = STORAGE_DIR / filename

    with destination.open("wb") as output:
        shutil.copyfileobj(file.file, output)

    return str(destination)


def validate_document(path: str, content_type: str) -> None:
    """Verify the stored bytes really are the declared type. Raise ValueError if not.

    MIME headers are client-controlled; a renamed .exe can claim image/png.
    """
    if content_type == "application/pdf":
        with open(path, "rb") as handle:
            if handle.read(5) != b"%PDF-":
                raise ValueError("not a valid PDF (missing %PDF- signature)")
        return

    expected = _IMAGE_FORMAT.get(content_type)
    if expected is None:  # unreachable while allowed_types is the gate; defensive
        raise ValueError(f"unsupported content type {content_type}")
    try:
        with Image.open(path) as image:
            image.verify()  # checks structure/decodability without full decode
            fmt = image.format
    except Exception as exc:  # PIL raises many types for corrupt input
        raise ValueError(f"not a valid image: {exc}") from exc
    if fmt != expected:
        raise ValueError(f"file is a {fmt}, not the declared {expected}")
