import io
import os
import pathlib
import tempfile

_TMP = tempfile.mkdtemp(prefix="fh-test-")
os.environ["DATABASE_URL"] = f"sqlite:///{_TMP}/test.db"
os.environ["STORAGE_DIR"] = f"{_TMP}/documents"

# Schema comes from the migrations against an empty DB — same path as production,
# and this doubles as the "migration on a clean DB" check (see the test below).
from alembic import command
from alembic.config import Config

command.upgrade(Config("alembic.ini"), "head")

from fastapi.testclient import TestClient
from PIL import Image

import app.main as main

client = TestClient(main.app)


# --- fixtures / helpers ------------------------------------------------------

def png_bytes() -> bytes:
    buf = io.BytesIO()
    Image.new("RGB", (12, 12), "white").save(buf, "PNG")
    return buf.getvalue()


def jpeg_bytes() -> bytes:
    buf = io.BytesIO()
    Image.new("RGB", (12, 12), "white").save(buf, "JPEG")
    return buf.getvalue()


# Smallest thing with a real %PDF- signature; PDFs are stored, never OCR'd.
PDF_BYTES = b"%PDF-1.4\n1 0 obj<<>>endobj\ntrailer<<>>\n%%EOF\n"


def upload(member_id: int, content: bytes = None, ctype: str = "image/png", name: str = "rx.png"):
    return client.post(
        f"/family-members/{member_id}/prescriptions/upload",
        files={"file": (name, content if content is not None else png_bytes(), ctype)},
    )


def make_member(name: str = "T") -> int:
    return client.post("/family-members", json={"name": name}).json()["id"]


def rx_base(member_id: int, prescription_id: int) -> str:
    return f"/family-members/{member_id}/prescriptions/{prescription_id}"


# --- schema / migrations -----------------------------------------------------

def test_migration_applied_on_clean_db():
    from sqlalchemy import inspect
    from app.database import engine

    insp = inspect(engine)
    assert {
        "family_members", "prescriptions", "prescription_medicines",
        "medicine_inventory", "alembic_version",
    } <= set(insp.get_table_names())
    cols = {c["name"] for c in insp.get_columns("prescriptions")}
    assert {"ocr_text", "ocr_error", "ocr_edited"} <= cols


# --- health ------------------------------------------------------------------

def test_health():
    assert client.get("/health").json() == {"status": "ok"}


def test_health_db():
    assert client.get("/health/db").json() == {"database": True}


# --- members / prescriptions / isolation ------------------------------------

def test_create_and_list_member():
    mid = make_member("Member-A")
    names = [m["name"] for m in client.get("/family-members").json()]
    assert "Member-A" in names
    assert isinstance(mid, int)


def test_prescription_created_only_for_its_member():
    m1, m2 = make_member("ISO-1"), make_member("ISO-2")
    body = {
        "document_path": "/data/documents/x.png",
        "doctor_name": "Dr. Kumar",
        "medicines": [{"medicine_name": "Paracetamol", "dosage": "500 mg"}],
    }
    created = client.post(f"/family-members/{m1}/prescriptions", json=body)
    assert created.status_code == 200

    rx1 = client.get(f"/family-members/{m1}/prescriptions").json()
    rx2 = client.get(f"/family-members/{m2}/prescriptions").json()
    assert len(rx1) == 1
    assert rx2 == []
    assert rx1[0]["medicines"][0]["medicine_name"] == "Paracetamol"


def test_upload_missing_member():
    assert upload(999_999).status_code == 404


def test_prescription_isolation_across_members():
    """A prescription owned by m1 must be unreachable via m2 on every route."""
    m1, m2 = make_member("OWNER"), make_member("INTRUDER")
    data = upload(m1).json()
    pid = data["prescription_id"]

    assert client.get(rx_base(m2, pid) + "/document").status_code == 404
    assert client.patch(rx_base(m2, pid), json={"ocr_text": "x"}).status_code == 404
    assert client.post(rx_base(m2, pid) + "/ocr").status_code == 404
    assert client.delete(rx_base(m2, pid)).status_code == 404

    # none of that touched the real owner's record or file
    rx = client.get(f"/family-members/{m1}/prescriptions").json()
    assert len(rx) == 1
    assert pathlib.Path(data["stored_path"]).exists()


# --- upload content validation ----------------------------------------------

def test_upload_valid_png():
    mid = make_member("PNG")
    res = upload(mid, png_bytes(), "image/png", "rx.png")
    assert res.status_code == 200
    assert pathlib.Path(res.json()["stored_path"]).exists()


def test_upload_valid_jpeg():
    mid = make_member("JPEG")
    res = upload(mid, jpeg_bytes(), "image/jpeg", "rx.jpg")
    assert res.status_code == 200
    assert pathlib.Path(res.json()["stored_path"]).exists()


def test_upload_valid_pdf_is_stored_not_ocrd():
    mid = make_member("PDF")
    res = upload(mid, PDF_BYTES, "application/pdf", "rx.pdf")
    assert res.status_code == 200
    data = res.json()
    assert data["ocr_text"] is None and data["ocr_error"] is None
    assert pathlib.Path(data["stored_path"]).exists()


def test_upload_fake_jpeg_renamed_rejected():
    # PNG bytes claiming to be a JPEG → content check catches the mismatch.
    mid = make_member("FAKE-JPG")
    res = upload(mid, png_bytes(), "image/jpeg", "rx.jpg")
    assert res.status_code == 400
    assert client.get(f"/family-members/{mid}/prescriptions").json() == []


def test_upload_corrupt_image_rejected():
    mid = make_member("CORRUPT")
    res = upload(mid, b"this is not an image", "image/png", "rx.png")
    assert res.status_code == 400
    assert client.get(f"/family-members/{mid}/prescriptions").json() == []


def test_upload_invalid_pdf_rejected():
    mid = make_member("BAD-PDF")
    res = upload(mid, b"definitely not a pdf", "application/pdf", "rx.pdf")
    assert res.status_code == 400
    assert client.get(f"/family-members/{mid}/prescriptions").json() == []


def test_upload_invalid_content_type_rejected():
    mid = make_member("BAD-TYPE")
    res = upload(mid, content=b"hello", ctype="text/plain", name="x.txt")
    assert res.status_code == 400


def test_rejected_upload_leaves_no_file():
    mid = make_member("NO-ORPHAN")
    before = set(pathlib.Path(os.environ["STORAGE_DIR"]).glob("*"))
    assert upload(mid, b"nope", "image/png", "rx.png").status_code == 400
    after = set(pathlib.Path(os.environ["STORAGE_DIR"]).glob("*"))
    assert before == after  # the corrupt file was unlinked


# --- OCR: success, failure tolerance, retry, manual edit ---------------------

def test_upload_ocr_success(monkeypatch):
    monkeypatch.setattr(main, "extract_text", lambda path: "Dr. Kumar\nParacetamol 500 mg")
    mid = make_member("OCR-OK")
    data = upload(mid).json()
    assert data["ocr_text"] == "Dr. Kumar\nParacetamol 500 mg"
    assert data["ocr_error"] is None

    rx = client.get(f"/family-members/{mid}/prescriptions").json()
    assert rx[0]["ocr_text"] == "Dr. Kumar\nParacetamol 500 mg"
    assert rx[0]["ocr_edited"] is False


def test_upload_ocr_failure_keeps_document_and_record(monkeypatch):
    def boom(path):
        raise RuntimeError("tesseract missing")

    monkeypatch.setattr(main, "extract_text", boom)
    mid = make_member("OCR-FAIL")
    res = upload(mid)
    assert res.status_code == 200  # OCR failure must not fail the upload
    data = res.json()
    assert data["ocr_text"] is None
    assert "tesseract missing" in data["ocr_error"]

    rx = client.get(f"/family-members/{mid}/prescriptions").json()
    assert len(rx) == 1
    assert rx[0]["ocr_text"] is None
    assert "tesseract missing" in rx[0]["ocr_error"]

    # original document is still retrievable after OCR failed
    doc = client.get(rx_base(mid, data["prescription_id"]) + "/document")
    assert doc.status_code == 200
    assert doc.content[:8] == b"\x89PNG\r\n\x1a\n"


def test_ocr_retry_success(monkeypatch):
    def boom(path):
        raise RuntimeError("tesseract missing")

    monkeypatch.setattr(main, "extract_text", boom)
    mid = make_member("RETRY-OK")
    pid = upload(mid).json()["prescription_id"]

    monkeypatch.setattr(main, "extract_text", lambda path: "recovered text")
    res = client.post(rx_base(mid, pid) + "/ocr")
    assert res.status_code == 200
    assert res.json()["ocr_text"] == "recovered text"
    assert res.json()["ocr_error"] is None

    rx = client.get(f"/family-members/{mid}/prescriptions").json()
    assert rx[0]["ocr_text"] == "recovered text"
    assert rx[0]["ocr_error"] is None
    assert rx[0]["ocr_edited"] is False
    # retry must not create a second prescription
    assert len(rx) == 1


def test_ocr_retry_failure_preserves_document(monkeypatch):
    monkeypatch.setattr(main, "extract_text", lambda path: "first pass")
    mid = make_member("RETRY-FAIL")
    data = upload(mid).json()
    pid = data["prescription_id"]

    def boom(path):
        raise RuntimeError("engine died")

    monkeypatch.setattr(main, "extract_text", boom)
    res = client.post(rx_base(mid, pid) + "/ocr")
    assert res.status_code == 200
    assert res.json()["ocr_text"] is None
    assert "engine died" in res.json()["ocr_error"]

    # document and record survive a failed retry
    assert pathlib.Path(data["stored_path"]).exists()
    assert client.get(rx_base(mid, pid) + "/document").status_code == 200


def test_ocr_retry_rejected_for_pdf():
    mid = make_member("RETRY-PDF")
    pid = upload(mid, PDF_BYTES, "application/pdf", "rx.pdf").json()["prescription_id"]
    assert client.post(rx_base(mid, pid) + "/ocr").status_code == 400


def test_manual_ocr_edit_persists(monkeypatch):
    monkeypatch.setattr(main, "extract_text", lambda path: "machine text")
    mid = make_member("MANUAL")
    pid = upload(mid).json()["prescription_id"]

    res = client.patch(rx_base(mid, pid), json={"ocr_text": "corrected by hand"})
    assert res.status_code == 200

    rx = client.get(f"/family-members/{mid}/prescriptions").json()
    assert rx[0]["ocr_text"] == "corrected by hand"
    assert rx[0]["ocr_edited"] is True  # distinguished from machine output
    assert rx[0]["ocr_error"] is None


def test_patch_updates_fields_and_isolates(monkeypatch):
    monkeypatch.setattr(main, "extract_text", lambda path: "x")
    mid = make_member("PATCH")
    pid = upload(mid).json()["prescription_id"]

    res = client.patch(rx_base(mid, pid), json={"doctor_name": "Dr. corrected"})
    assert res.status_code == 200
    rx = client.get(f"/family-members/{mid}/prescriptions").json()
    assert rx[0]["doctor_name"] == "Dr. corrected"

    # omitted fields untouched; explicit empty clears
    client.patch(rx_base(mid, pid), json={"ocr_text": ""})
    rx = client.get(f"/family-members/{mid}/prescriptions").json()
    assert rx[0]["ocr_text"] == ""
    assert rx[0]["doctor_name"] == "Dr. corrected"

    assert client.patch(rx_base(mid, pid), json={"prescription_date": "nope"}).status_code == 422
    assert client.patch(rx_base(mid, 999999), json={"ocr_text": "x"}).status_code == 404


# --- document retrieval / path traversal ------------------------------------

def test_document_endpoint_serves_image():
    mid = make_member("DOC")
    data = upload(mid).json()
    res = client.get(rx_base(mid, data["prescription_id"]) + "/document")
    assert res.status_code == 200
    assert res.headers["content-type"].startswith("image/png")
    assert res.headers["x-content-type-options"] == "nosniff"
    assert res.content[:8] == b"\x89PNG\r\n\x1a\n"


def test_document_endpoint_404s_and_blocks_traversal():
    mid = make_member("ESCAPE")
    assert client.get(rx_base(mid, 999999) + "/document").status_code == 404

    # a record pointing outside STORAGE_DIR must never be served
    from app.database import SessionLocal
    from app.models import Prescription

    with SessionLocal() as session:
        session.add(Prescription(family_member_id=mid, document_path="/etc/hosts"))
        session.commit()
    rx = client.get(f"/family-members/{mid}/prescriptions").json()
    assert client.get(rx_base(mid, rx[0]["id"]) + "/document").status_code == 404


# --- delete (cascade + file removal + isolation) -----------------------------

def test_delete_removes_record_file_and_medicines(monkeypatch):
    monkeypatch.setattr(main, "extract_text", lambda path: "x")
    mid = make_member("DELETE")
    uploaded = upload(mid).json()
    pid, stored = uploaded["prescription_id"], uploaded["stored_path"]
    rx2_id = client.post(
        f"/family-members/{mid}/prescriptions",
        json={
            "document_path": "/data/documents/x.png",
            "medicines": [{"medicine_name": "Ibuprofen"}],
        },
    ).json()["id"]

    assert pathlib.Path(stored).exists()

    # deleting the medicine-bearing prescription cascades to its medicines
    assert client.delete(rx_base(mid, rx2_id)).status_code == 200
    from sqlalchemy import func, select
    from app.database import SessionLocal
    from app.models import PrescriptionMedicine

    with SessionLocal() as session:
        orphans = session.scalar(
            select(func.count())
            .select_from(PrescriptionMedicine)
            .where(PrescriptionMedicine.prescription_id == rx2_id)
        )
    assert orphans == 0

    # deleting the uploaded prescription removes the stored file
    assert client.delete(rx_base(mid, pid)).status_code == 200
    assert not pathlib.Path(stored).exists()
    assert client.get(rx_base(mid, pid) + "/document").status_code == 404
    assert client.delete(rx_base(mid, pid)).status_code == 404

    remaining = [r["id"] for r in client.get(f"/family-members/{mid}/prescriptions").json()]
    assert pid not in remaining and rx2_id not in remaining


# --- inventory ---------------------------------------------------------------

def test_inventory_add_and_list():
    res = client.post(
        "/inventory",
        json={
            "medicine_name": "Paracetamol-INV",
            "quantity": 10,
            "unit": "tablets",
            "expiry_date": "2027-05-01",
        },
    )
    assert res.status_code == 201
    items = client.get("/inventory").json()
    names = [i["medicine_name"] for i in items]
    assert "Paracetamol-INV" in names
    assert next(i for i in items if i["medicine_name"] == "Paracetamol-INV")["source"] == "manual"


def test_inventory_requires_name():
    assert client.post("/inventory", json={"quantity": 5}).status_code == 422
