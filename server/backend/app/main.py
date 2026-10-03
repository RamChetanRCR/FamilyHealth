from datetime import date

from fastapi import FastAPI, HTTPException, UploadFile, File, UploadFile, File
from pydantic import BaseModel, Field
from sqlalchemy import select

from app.database import SessionLocal, engine
from app.storage import save_document
from app.ocr import extract_text
from app.storage import save_document
from app.ocr import extract_text
from app.models import (
    Base,
    FamilyMember,
    Prescription,
    PrescriptionMedicine,
)

Base.metadata.create_all(bind=engine)

app = FastAPI(title="Family Health API")


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
                    "doctor_name": prescription.doctor_name,
                    "hospital_name": prescription.hospital_name,
                    "diagnosis": prescription.diagnosis,
                    "notes": prescription.notes,
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
):
    with SessionLocal() as session:
        member = session.get(FamilyMember, member_id)

        if member is None:
            raise HTTPException(404, "Family member not found")

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

        ocr_text = ""
        if file.content_type.startswith("image/"):
            ocr_text = extract_text(path)

        prescription = Prescription(
            family_member_id=member_id,
            document_path=path,
            notes="OCR text extracted during upload.",
        )

        session.add(prescription)
        session.commit()
        session.refresh(prescription)

        with open(path, "rb"):
            pass

        session.execute(
            Prescription.__table__.update()
            .where(Prescription.id == prescription.id)
            .values(ocr_text=ocr_text)
        )
        session.commit()

        return {
            "message": "Prescription uploaded",
            "family_member_id": member_id,
            "prescription_id": prescription.id,
            "filename": file.filename,
            "stored_path": path,
            "ocr_text": ocr_text,
        }
