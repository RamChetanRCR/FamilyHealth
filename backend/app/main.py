from datetime import date
from pathlib import Path

from fastapi import FastAPI, HTTPException, UploadFile, File, Form
from fastapi.responses import FileResponse
from pydantic import BaseModel, Field
from sqlalchemy import delete, select

from app.database import SessionLocal, engine
from app.storage import save_document, validate_document, STORAGE_DIR
from app.ocr import extract_text
from app.models import (
    FamilyMember,
    MedicineInventory,
    Prescription,
    PrescriptionMedicine,
)

app = FastAPI(title="Family Health API")


def _owned_prescription(session, member_id: int, prescription_id: int) -> Prescription:
    """Load a prescription only if it belongs to member_id — the single
    member→prescription access boundary. Later auth checks the caller here."""
    rx = session.get(Prescription, prescription_id)
    if rx is None or rx.family_member_id != member_id:
        raise HTTPException(404, "Prescription not found")
    return rx


def _run_ocr(path: str, content_type: str | None) -> tuple[str | None, str | None]:
    """(ocr_text, ocr_error) — never raises; OCR failure must not lose the document."""
    if not (content_type or "").startswith("image/"):
        return None, None  # PDFs/others stored without OCR; not an error
    try:
        return extract_text(path), None
    except Exception as exc:  # ponytail: broad — any OCR failure keeps doc+record
        return None, str(exc) or type(exc).__name__


class FamilyMemberCreate(BaseModel):
    name: str
    date_of_birth: date | None = None
    gender: str | None = None


class PrescriptionMedicineCreate(BaseModel):
    medicine_name: str
    dosage: str | None = None
    frequency: str | None = None
    duration: str | None = None
    instructions: str | None = None


class PrescriptionCreate(BaseModel):
    document_path: str
    prescription_date: date | None = None
    doctor_name: str | None = None
    hospital_name: str | None = None
    diagnosis: str | None = None
    notes: str | None = None
    medicines: list[PrescriptionMedicineCreate] = Field(default_factory=list)


class MedicineInventoryCreate(BaseModel):
    medicine_name: str
    quantity: int | None = None
    unit: str | None = None
    expiry_date: date | None = None
    source: str = "manual"


@app.get("/health")
def health():
    return {"status": "ok"}


@app.get("/health/db")
def database_health():
    with engine.connect() as connection:
        connection.exec_driver_sql("SELECT 1")
        return {"database": True}


@app.post("/family-members")
def create_family_member(member: FamilyMemberCreate):
    with SessionLocal() as session:
        new_member = FamilyMember(
            name=member.name,
            date_of_birth=member.date_of_birth,
            gender=member.gender,
        )
        session.add(new_member)
        session.commit()
        session.refresh(new_member)

        return {
            "id": new_member.id,
            "name": new_member.name,
            "date_of_birth": new_member.date_of_birth,
            "gender": new_member.gender,
        }


@app.get("/family-members")
def list_family_members():
    with SessionLocal() as session:
        members = session.scalars(
            select(FamilyMember).order_by(FamilyMember.id)
        ).all()

        return [
            {
                "id": member.id,
                "name": member.name,
                "date_of_birth": member.date_of_birth,
                "gender": member.gender,
            }
            for member in members
        ]


@app.post("/family-members/{member_id}/prescriptions")
def create_prescription(
    member_id: int,
    prescription: PrescriptionCreate,
):
    with SessionLocal() as session:
        member = session.get(FamilyMember, member_id)

        if member is None:
            raise HTTPException(404, "Family member not found")

        new_prescription = Prescription(
            family_member_id=member_id,
            document_path=prescription.document_path,
            prescription_date=prescription.prescription_date,
            doctor_name=prescription.doctor_name,
            hospital_name=prescription.hospital_name,
            diagnosis=prescription.diagnosis,
            notes=prescription.notes,
        )

        session.add(new_prescription)
        session.flush()

        for medicine in prescription.medicines:
            session.add(
                PrescriptionMedicine(
                    prescription_id=new_prescription.id,
                    medicine_name=medicine.medicine_name,
                    dosage=medicine.dosage,
                    frequency=medicine.frequency,
                    duration=medicine.duration,
                    instructions=medicine.instructions,
                )
            )

        session.commit()
        session.refresh(new_prescription)

        medicines = session.scalars(
            select(PrescriptionMedicine).where(
                PrescriptionMedicine.prescription_id
                == new_prescription.id
            )
        ).all()

        return {
            "id": new_prescription.id,
            "family_member_id": member_id,
            "prescription_date": new_prescription.prescription_date,
            "doctor_name": new_prescription.doctor_name,
            "hospital_name": new_prescription.hospital_name,
            "diagnosis": new_prescription.diagnosis,
            "notes": new_prescription.notes,
            "medicines": [
                {
                    "medicine_name": medicine.medicine_name,
                    "dosage": medicine.dosage,
                    "frequency": medicine.frequency,
                    "duration": medicine.duration,
                    "instructions": medicine.instructions,
                }
                for medicine in medicines
            ],
        }


@app.get("/family-members/{member_id}/prescriptions")
def get_member_prescriptions(member_id: int):
    with SessionLocal() as session:
        if session.get(FamilyMember, member_id) is None:
            raise HTTPException(404, "Family member not found")

        prescriptions = session.scalars(
            select(Prescription)
            .where(Prescription.family_member_id == member_id)
            .order_by(Prescription.prescription_date.desc())
        ).all()

        result = []

        for prescription in prescriptions:
            medicines = session.scalars(
                select(PrescriptionMedicine).where(
                    PrescriptionMedicine.prescription_id
                    == prescription.id
                )
            ).all()

            result.append(
                {
                    "id": prescription.id,
                    "prescription_date": prescription.prescription_date,
                    "created_at": prescription.created_at,
                    "doctor_name": prescription.doctor_name,
                    "hospital_name": prescription.hospital_name,
                    "diagnosis": prescription.diagnosis,
                    "notes": prescription.notes,
                    "ocr_text": prescription.ocr_text,
                    "ocr_error": prescription.ocr_error,
                    "ocr_edited": prescription.ocr_edited,
                    "medicines": [
                        {
                            "medicine_name": medicine.medicine_name,
                            "dosage": medicine.dosage,
                            "frequency": medicine.frequency,
                            "duration": medicine.duration,
                            "instructions": medicine.instructions,
                        }
                        for medicine in medicines
                    ],
                }
            )

        return result


@app.post("/family-members/{member_id}/prescriptions/upload")
def upload_prescription(
    member_id: int,
    file: UploadFile = File(...),
    prescription_date: str | None = Form(None),
):
    with SessionLocal() as session:
        member = session.get(FamilyMember, member_id)

        if member is None:
            raise HTTPException(404, "Family member not found")

        rx_date = None
        if prescription_date:
            try:
                rx_date = date.fromisoformat(prescription_date)
            except ValueError:
                raise HTTPException(400, "prescription_date must be YYYY-MM-DD")
        if rx_date is None:
            rx_date = date.today()  # upload date; user can PATCH a different one

        allowed_types = {
            "image/jpeg",
            "image/png",
            "application/pdf",
        }

        if file.content_type not in allowed_types:
            raise HTTPException(
                400,
                "Only JPEG, PNG, and PDF files are allowed",
            )

        path = save_document(file)

        # Content, not just the client-declared MIME type: reject renamed/corrupt
        # files and never keep them on disk.
        try:
            validate_document(path, file.content_type)
        except ValueError as exc:
            Path(path).unlink(missing_ok=True)
            raise HTTPException(400, f"Invalid file: {exc}")

        ocr_text, ocr_error = _run_ocr(path, file.content_type)
        notes = (
            "PDF stored; text extraction not implemented yet."
            if file.content_type == "application/pdf"
            else None
        )

        prescription = Prescription(
            family_member_id=member_id,
            document_path=path,
            prescription_date=rx_date,
            ocr_text=ocr_text,
            ocr_error=ocr_error,
            notes=notes,
        )

        session.add(prescription)
        session.commit()
        session.refresh(prescription)

        return {
            "message": "Prescription uploaded",
            "family_member_id": member_id,
            "prescription_id": prescription.id,
            "filename": file.filename,
            "stored_path": path,
            "prescription_date": prescription.prescription_date,
            "ocr_text": ocr_text,
            "ocr_error": ocr_error,
        }


ALLOWED_DOCUMENT_EXTENSIONS = {".jpg", ".jpeg", ".png", ".pdf"}


class PrescriptionUpdate(BaseModel):
    prescription_date: date | None = None
    doctor_name: str | None = None
    hospital_name: str | None = None
    diagnosis: str | None = None
    ocr_text: str | None = None


@app.patch("/family-members/{member_id}/prescriptions/{prescription_id}")
def update_prescription(
    member_id: int, prescription_id: int, update: PrescriptionUpdate
):
    with SessionLocal() as session:
        prescription = _owned_prescription(session, member_id, prescription_id)

        changes = update.model_dump(exclude_unset=True)
        for field, value in changes.items():
            setattr(prescription, field, value)
        if "ocr_text" in changes:  # manual correction: flag it, clear stale error
            prescription.ocr_edited = True
            prescription.ocr_error = None
        session.commit()
        return {"id": prescription_id, "updated": sorted(changes)}


@app.post("/family-members/{member_id}/prescriptions/{prescription_id}/ocr")
def retry_ocr(member_id: int, prescription_id: int):
    """Re-run OCR on the already-stored document. No new record, no re-upload."""
    with SessionLocal() as session:
        prescription = _owned_prescription(session, member_id, prescription_id)

        path = Path(prescription.document_path).resolve()
        if not (
            path.is_relative_to(STORAGE_DIR.resolve())
            and path.suffix.lower() in ALLOWED_DOCUMENT_EXTENSIONS
            and path.is_file()
        ):
            raise HTTPException(404, "Stored document not available")
        if path.suffix.lower() == ".pdf":
            raise HTTPException(400, "OCR not supported for PDF documents")

        ocr_text, ocr_error = _run_ocr(str(path), "image/")
        prescription.ocr_text = ocr_text
        prescription.ocr_error = ocr_error
        prescription.ocr_edited = False  # machine-generated again
        session.commit()
        return {
            "id": prescription_id,
            "ocr_text": ocr_text,
            "ocr_error": ocr_error,
        }


@app.delete("/family-members/{member_id}/prescriptions/{prescription_id}")
def delete_prescription(member_id: int, prescription_id: int):
    with SessionLocal() as session:
        prescription = _owned_prescription(session, member_id, prescription_id)

        document_path = Path(prescription.document_path).resolve()
        session.execute(
            delete(PrescriptionMedicine).where(
                PrescriptionMedicine.prescription_id == prescription_id
            )
        )
        session.delete(prescription)
        session.commit()

    # remove the stored file only if it is inside STORAGE_DIR
    if document_path.is_relative_to(STORAGE_DIR.resolve()):
        document_path.unlink(missing_ok=True)
    return {"deleted": prescription_id}


@app.get("/family-members/{member_id}/prescriptions/{prescription_id}/document")
def get_prescription_document(member_id: int, prescription_id: int):
    with SessionLocal() as session:
        prescription = _owned_prescription(session, member_id, prescription_id)

        path = Path(prescription.document_path).resolve()
        # never serve anything outside STORAGE_DIR or with a dangerous suffix
        if (
            path.suffix.lower() not in ALLOWED_DOCUMENT_EXTENSIONS
            or not path.is_relative_to(STORAGE_DIR.resolve())
            or not path.is_file()
        ):
            raise HTTPException(404, "Document not available")

        return FileResponse(path, headers={"X-Content-Type-Options": "nosniff"})


@app.get("/inventory")
def list_inventory():
    with SessionLocal() as session:
        rows = session.scalars(
            select(MedicineInventory).order_by(MedicineInventory.medicine_name)
        ).all()
        return [
            {
                "id": row.id,
                "medicine_name": row.medicine_name,
                "quantity": row.quantity,
                "unit": row.unit,
                "expiry_date": row.expiry_date,
                "source": row.source,
            }
            for row in rows
        ]


@app.post("/inventory", status_code=201)
def add_inventory_item(item: MedicineInventoryCreate):
    with SessionLocal() as session:
        row = MedicineInventory(
            medicine_name=item.medicine_name,
            quantity=item.quantity,
            unit=item.unit,
            expiry_date=item.expiry_date,
            source=item.source,
        )
        session.add(row)
        session.commit()
        session.refresh(row)
        return {
            "id": row.id,
            "medicine_name": row.medicine_name,
            "quantity": row.quantity,
            "unit": row.unit,
            "expiry_date": row.expiry_date,
            "source": row.source,
        }
