from datetime import date, datetime

from sqlalchemy import Date, DateTime, ForeignKey, Integer, String, Text
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


class Base(DeclarativeBase):
    pass


class FamilyMember(Base):
    __tablename__ = "family_members"

    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(100), nullable=False)
    date_of_birth: Mapped[date | None] = mapped_column(Date, nullable=True)
    gender: Mapped[str | None] = mapped_column(String(20), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime, default=datetime.utcnow
    )


class Prescription(Base):
    __tablename__ = "prescriptions"

    id: Mapped[int] = mapped_column(primary_key=True)
    family_member_id: Mapped[int] = mapped_column(
        ForeignKey("family_members.id"),
        nullable=False,
        index=True,
    )
    document_path: Mapped[str] = mapped_column(
        String(500),
        nullable=False,
    )
    prescription_date: Mapped[date | None] = mapped_column(
        Date,
        nullable=True,
    )
    doctor_name: Mapped[str | None] = mapped_column(
        String(150),
        nullable=True,
    )
    hospital_name: Mapped[str | None] = mapped_column(
        String(200),
        nullable=True,
    )
    diagnosis: Mapped[str | None] = mapped_column(
        Text,
        nullable=True,
    )
    notes: Mapped[str | None] = mapped_column(
        Text,
        nullable=True,
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime,
        default=datetime.utcnow,
    )


class PrescriptionMedicine(Base):
    __tablename__ = "prescription_medicines"

    id: Mapped[int] = mapped_column(primary_key=True)
    prescription_id: Mapped[int] = mapped_column(
        ForeignKey("prescriptions.id"),
        nullable=False,
        index=True,
    )
    medicine_name: Mapped[str] = mapped_column(
        String(200),
        nullable=False,
    )
    dosage: Mapped[str | None] = mapped_column(
        String(100),
        nullable=True,
    )
    frequency: Mapped[str | None] = mapped_column(
        String(100),
        nullable=True,
    )
    duration: Mapped[str | None] = mapped_column(
        String(100),
        nullable=True,
    )
    instructions: Mapped[str | None] = mapped_column(
        Text,
        nullable=True,
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime,
        default=datetime.utcnow,
    )


class MedicineInventory(Base):
    __tablename__ = "medicine_inventory"

    id: Mapped[int] = mapped_column(primary_key=True)
    medicine_name: Mapped[str] = mapped_column(
        String(200),
        nullable=False,
    )
    quantity: Mapped[int | None] = mapped_column(
        Integer,
        nullable=True,
    )
    unit: Mapped[str | None] = mapped_column(
        String(50),
        nullable=True,
    )
    expiry_date: Mapped[date | None] = mapped_column(
        Date,
        nullable=True,
    )
    source: Mapped[str | None] = mapped_column(
        String(50),
        nullable=True,
    )
    image_path: Mapped[str | None] = mapped_column(
        String(500),
        nullable=True,
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime,
        default=datetime.utcnow,
    )
