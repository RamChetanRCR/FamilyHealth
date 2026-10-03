import io
import os
import pathlib
import tempfile

_TMP = tempfile.mkdtemp(prefix="fh-test-")
os.environ["DATABASE_URL"] = f"sqlite:///{_TMP}/test.db"
os.environ["STORAGE_DIR"] = f"{_TMP}/documents"

import pytest
from fastapi.testclient import TestClient
from PIL import Image

import app.main as main

client = TestClient(main.app)


def png_bytes() -> bytes:
    buf = io.BytesIO()
    Image.new("RGB", (12, 12), "white").save(buf, "PNG")
    return buf.getvalue()


def upload(member_id: int, content: bytes = None, ctype: str = "image/png", name: str = "rx.png"):
    return client.post(
        f"/family-members/{member_id}/prescriptions/upload",
        files={"file": (name, content if content is not None else png_bytes(), ctype)},
    )


def make_member(name: str = "T") -> int:
    return client.post("/family-members", json={"name": name}).json()["id"]


def test_health():
    assert client.get("/health").json() == {"status": "ok"}


def test_health_db():
    assert client.get("/health/db").json() == {"database": True}


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


def test_upload_ocr_success(monkeypatch):
    monkeypatch.setattr(main, "extract_text", lambda path: "Dr. Kumar\nParacetamol 500 mg")
    mid = make_member("OCR-OK")
    res = upload(mid)
    assert res.status_code == 200
    data = res.json()
    assert data["ocr_text"] == "Dr. Kumar\nParacetamol 500 mg"
    assert data["ocr_error"] is None
    assert pathlib.Path(data["stored_path"]).exists()

    rx = client.get(f"/family-members/{mid}/prescriptions").json()
    assert rx[0]["ocr_text"] == "Dr. Kumar\nParacetamol 500 mg"


def test_upload_ocr_failure_keeps_document(monkeypatch):
    def boom(path):
        raise RuntimeError("tesseract missing")

    monkeypatch.setattr(main, "extract_text", boom)
    mid = make_member("OCR-FAIL")
    res = upload(mid)
    assert res.status_code == 200
    data = res.json()
    assert data["ocr_text"] is None
    assert "tesseract missing" in data["ocr_error"]
    assert pathlib.Path(data["stored_path"]).exists()

    rx = client.get(f"/family-members/{mid}/prescriptions").json()
    assert rx[0]["ocr_text"] is None
    assert rx[0]["notes"].startswith("OCR failed")


def test_upload_invalid_file_rejected():
    mid = make_member("BAD-FILE")
    res = upload(mid, content=b"not an image", ctype="text/plain", name="x.txt")
    assert res.status_code == 400
    assert client.get(f"/family-members/{mid}/prescriptions").json() == []


def test_upload_missing_member():
    assert upload(999_999).status_code == 404


def test_upload_with_prescription_date():
    from datetime import date

    mid = make_member("DATED")
    res = upload(mid)
    assert res.status_code == 200
    # no date given → stores the upload date, never null
    assert res.json()["prescription_date"] == date.today().isoformat()

    res = client.post(
        f"/family-members/{mid}/prescriptions/upload",
        data={"prescription_date": "2026-09-15"},
        files={"file": ("rx.png", png_bytes(), "image/png")},
    )
    assert res.status_code == 200
    assert res.json()["prescription_date"] == "2026-09-15"
    rx = client.get(f"/family-members/{mid}/prescriptions").json()
    assert any(r["prescription_date"] == "2026-09-15" for r in rx)
    assert all(r["created_at"] for r in rx)


def test_upload_invalid_date_rejected():
    mid = make_member("BAD-DATE")
    res = client.post(
        f"/family-members/{mid}/prescriptions/upload",
        data={"prescription_date": "not-a-date"},
        files={"file": ("rx.png", png_bytes(), "image/png")},
    )
    assert res.status_code == 400


def test_document_endpoint_serves_image():
    mid = make_member("DOC")
    data = upload(mid).json()
    res = client.get(f"/prescriptions/{data['prescription_id']}/document")
    assert res.status_code == 200
    assert res.headers["content-type"].startswith("image/png")
    assert res.headers["x-content-type-options"] == "nosniff"
    assert res.content[:8] == b"\x89PNG\r\n\x1a\n"


def test_document_endpoint_404s():
    assert client.get("/prescriptions/999999/document").status_code == 404
    # record pointing outside STORAGE_DIR must never be served
    from app.database import SessionLocal
    from app.models import Prescription

    mid = make_member("ESCAPE")
    with SessionLocal() as session:
        session.add(Prescription(family_member_id=mid, document_path="/etc/hosts"))
        session.commit()
    rx = client.get(f"/family-members/{mid}/prescriptions").json()
    assert client.get(f"/prescriptions/{rx[0]['id']}/document").status_code == 404


def test_inventory_add_and_list():
    assert client.get("/inventory").json() == []
    res = client.post(
        "/inventory",
        json={
            "medicine_name": "Paracetamol",
            "quantity": 10,
            "unit": "tablets",
            "expiry_date": "2027-05-01",
        },
    )
    assert res.status_code == 201
    items = client.get("/inventory").json()
    assert len(items) == 1
    assert items[0]["medicine_name"] == "Paracetamol"
    assert items[0]["source"] == "manual"


def test_inventory_requires_name():
    assert client.post("/inventory", json={"quantity": 5}).status_code == 422


def test_patch_prescription_updates_fields():
    mid = make_member("PATCH")
    pid = upload(mid).json()["prescription_id"]
    res = client.patch(
        f"/prescriptions/{pid}",
        json={"ocr_text": "corrected text", "doctor_name": "Dr. corrected"},
    )
    assert res.status_code == 200
    rx = client.get(f"/family-members/{mid}/prescriptions").json()
    assert rx[0]["ocr_text"] == "corrected text"
    assert rx[0]["doctor_name"] == "Dr. corrected"

    # omitted fields stay untouched, explicit null clears
    client.patch(f"/prescriptions/{pid}", json={"ocr_text": ""})
    rx = client.get(f"/family-members/{mid}/prescriptions").json()
    assert rx[0]["ocr_text"] == ""
    assert rx[0]["doctor_name"] == "Dr. corrected"

    assert client.patch(f"/prescriptions/{pid}", json={"prescription_date": "nope"}).status_code == 422
    assert client.patch("/prescriptions/999999", json={"ocr_text": "x"}).status_code == 404


def test_delete_prescription_removes_record_file_and_medicines():
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

    ids_before = [r["id"] for r in client.get(f"/family-members/{mid}/prescriptions").json()]
    assert set(ids_before) == {pid, rx2_id}
    assert pathlib.Path(stored).exists()

    # deleting the medicine-bearing prescription cascades to its medicines
    assert client.delete(f"/prescriptions/{rx2_id}").status_code == 200
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
    assert client.delete(f"/prescriptions/{pid}").status_code == 200
    assert not pathlib.Path(stored).exists()
    assert client.get(f"/prescriptions/{pid}/document").status_code == 404
    assert client.delete(f"/prescriptions/{pid}").status_code == 404

    remaining = [r["id"] for r in client.get(f"/family-members/{mid}/prescriptions").json()]
    assert pid not in remaining and rx2_id not in remaining
