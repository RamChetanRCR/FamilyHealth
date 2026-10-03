from pathlib import Path
import shutil
from uuid import uuid4

STORAGE_DIR = Path("/data/documents")


def save_document(file):
    STORAGE_DIR.mkdir(parents=True, exist_ok=True)

    extension = Path(file.filename or "").suffix.lower()
    filename = f"{uuid4().hex}{extension}"
    destination = STORAGE_DIR / filename

    with destination.open("wb") as output:
        shutil.copyfileobj(file.file, output)

    return str(destination)
