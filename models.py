"""
database/models.py — SQLAlchemy ORM models
"""

from datetime import datetime
from sqlalchemy import (
    Column, Integer, String, Text, DateTime, Boolean,
    Float, ForeignKey, Enum as SAEnum
)
from sqlalchemy.orm import declarative_base, relationship
import enum

Base = declarative_base()


class UserRole(str, enum.Enum):
    patient = "patient"
    caregiver = "caregiver"
    doctor = "doctor"


class User(Base):
    __tablename__ = "users"

    id = Column(Integer, primary_key=True, autoincrement=True)
    username = Column(String(80), unique=True, nullable=False, index=True)
    full_name = Column(String(150), nullable=False)
    email = Column(String(150), unique=True, nullable=False)
    password_hash = Column(String(256), nullable=False)
    role = Column(SAEnum(UserRole), nullable=False, default=UserRole.patient)
    conditions = Column(Text, default="")          # comma-separated chronic conditions
    alert_threshold = Column(Float, default=75.0)  # % below which alerts are triggered
    created_at = Column(DateTime, default=datetime.utcnow)
    is_active = Column(Boolean, default=True)

    # relationships
    medications = relationship("Medication", back_populates="patient",
                               foreign_keys="Medication.patient_id",
                               cascade="all, delete-orphan")
    logs = relationship("MedicationLog", back_populates="patient",
                        foreign_keys="MedicationLog.patient_id",
                        cascade="all, delete-orphan")
    reminders = relationship("Reminder", back_populates="patient",
                             cascade="all, delete-orphan")
    # patients assigned to this caregiver/doctor
    assigned_patients = relationship(
        "PatientAssignment",
        foreign_keys="PatientAssignment.caregiver_id",
        back_populates="caregiver",
    )
    caregivers = relationship(
        "PatientAssignment",
        foreign_keys="PatientAssignment.patient_id",
        back_populates="patient_user",
    )


class Medication(Base):
    __tablename__ = "medications"

    id = Column(Integer, primary_key=True, autoincrement=True)
    patient_id = Column(Integer, ForeignKey("users.id"), nullable=False)
    name = Column(String(200), nullable=False)
    dosage = Column(String(100), nullable=False)
    frequency = Column(String(100), nullable=False)
    scheduled_times = Column(Text, default="")    # JSON list of "HH:MM" strings
    condition_tag = Column(String(100), default="")
    instructions = Column(Text, default="")
    start_date = Column(DateTime, nullable=False, default=datetime.utcnow)
    end_date = Column(DateTime, nullable=True)
    is_active = Column(Boolean, default=True)
    created_at = Column(DateTime, default=datetime.utcnow)

    patient = relationship("User", back_populates="medications",
                           foreign_keys=[patient_id])
    logs = relationship("MedicationLog", back_populates="medication",
                        cascade="all, delete-orphan")
    reminders = relationship("Reminder", back_populates="medication",
                             cascade="all, delete-orphan")


class MedicationLog(Base):
    __tablename__ = "medication_logs"

    id = Column(Integer, primary_key=True, autoincrement=True)
    patient_id = Column(Integer, ForeignKey("users.id"), nullable=False)
    medication_id = Column(Integer, ForeignKey("medications.id"), nullable=False)
    scheduled_time = Column(DateTime, nullable=False)
    taken_time = Column(DateTime, nullable=True)
    status = Column(String(20), nullable=False, default="pending")
    # status: "taken" | "missed" | "skipped" | "pending"
    notes = Column(Text, default="")
    side_effects = Column(Text, default="")
    created_at = Column(DateTime, default=datetime.utcnow)

    patient = relationship("User", back_populates="logs",
                           foreign_keys=[patient_id])
    medication = relationship("Medication", back_populates="logs")


class Reminder(Base):
    __tablename__ = "reminders"

    id = Column(Integer, primary_key=True, autoincrement=True)
    patient_id = Column(Integer, ForeignKey("users.id"), nullable=False)
    medication_id = Column(Integer, ForeignKey("medications.id"), nullable=False)
    reminder_time = Column(DateTime, nullable=False)
    minutes_before = Column(Integer, default=15)
    message = Column(Text, default="")
    is_sent = Column(Boolean, default=False)
    is_dismissed = Column(Boolean, default=False)
    created_at = Column(DateTime, default=datetime.utcnow)

    patient = relationship("User", back_populates="reminders")
    medication = relationship("Medication", back_populates="reminders")


class PatientAssignment(Base):
    """Links caregivers / doctors to patients they monitor."""
    __tablename__ = "patient_assignments"

    id = Column(Integer, primary_key=True, autoincrement=True)
    patient_id = Column(Integer, ForeignKey("users.id"), nullable=False)
    caregiver_id = Column(Integer, ForeignKey("users.id"), nullable=False)
    assigned_at = Column(DateTime, default=datetime.utcnow)
    notes = Column(Text, default="")

    patient_user = relationship("User", foreign_keys=[patient_id],
                                back_populates="caregivers")
    caregiver = relationship("User", foreign_keys=[caregiver_id],
                             back_populates="assigned_patients")


class CaregiverPatientNote(Base):
    """
    Caregiver/doctor-authored notes for a specific patient.
    One row per (caregiver, patient) pair — upserted on save.
    """
    __tablename__ = "caregiver_patient_notes"

    id = Column(Integer, primary_key=True, autoincrement=True)
    caregiver_id = Column(Integer, ForeignKey("users.id"), nullable=False)
    patient_id = Column(Integer, ForeignKey("users.id"), nullable=False)

    # Patient profile fields editable by caregiver
    conditions      = Column(Text, default="")      # chronic conditions (override/append)
    allergies       = Column(Text, default="")      # drug / food allergies
    emergency_name  = Column(String(150), default="")
    emergency_phone = Column(String(50), default="")
    blood_type      = Column(String(10), default="")
    weight_kg       = Column(Float, nullable=True)
    height_cm       = Column(Float, nullable=True)

    # Care plan & free-form notes
    care_plan       = Column(Text, default="")      # structured care instructions
    clinical_notes  = Column(Text, default="")      # general clinical observations
    diet_notes      = Column(Text, default="")      # dietary restrictions / notes
    exercise_notes  = Column(Text, default="")      # physical activity guidance

    # Medication-level notes (JSON list of dicts)
    # Each dict: {med_id, name, dosage, times, special_instructions, notes}
    medication_notes = Column(Text, default="[]")

    updated_at = Column(DateTime, default=datetime.utcnow)
    created_at = Column(DateTime, default=datetime.utcnow)


class AIConversation(Base):
    """Stores AI chat history per user."""
    __tablename__ = "ai_conversations"

    id = Column(Integer, primary_key=True, autoincrement=True)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False)
    role = Column(String(20), nullable=False)   # "user" | "model"
    content = Column(Text, nullable=False)
    created_at = Column(DateTime, default=datetime.utcnow)
