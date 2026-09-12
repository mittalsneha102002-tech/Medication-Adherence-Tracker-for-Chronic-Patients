"""
database/db_manager.py — Database session factory and all CRUD helpers
"""

from __future__ import annotations

import json
from contextlib import contextmanager
from datetime import datetime, timedelta, timezone


def _utcnow() -> datetime:
    """Return current UTC time as a timezone-naive datetime (SQLite compatible)."""
    return datetime.now(timezone.utc).replace(tzinfo=None)


from typing import Optional

import bcrypt
from sqlalchemy import create_engine, func
from sqlalchemy.orm import sessionmaker, Session

from config import DATABASE_URL
from database.models import (
    Base, User, UserRole, Medication, MedicationLog,
    Reminder, PatientAssignment, AIConversation,
    CaregiverPatientNote,
)

# ── Engine & session factory ──────────────────────────────────────────────────
engine = create_engine(
    DATABASE_URL,
    connect_args={"check_same_thread": False},   # SQLite only
    echo=False,
)
SessionLocal = sessionmaker(bind=engine, autocommit=False, autoflush=False)


def init_db() -> None:
    """Create all tables if they don't exist."""
    Base.metadata.create_all(bind=engine)


@contextmanager
def get_session():
    session: Session = SessionLocal()
    try:
        yield session
        session.commit()
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()


# ══════════════════════════════════════════════════════════════════════════════
# USER OPERATIONS
# ══════════════════════════════════════════════════════════════════════════════

def hash_password(plain: str) -> str:
    return bcrypt.hashpw(plain.encode(), bcrypt.gensalt()).decode()


def verify_password(plain: str, hashed: str) -> bool:
    return bcrypt.checkpw(plain.encode(), hashed.encode())


def create_user(
    username: str,
    full_name: str,
    email: str,
    password: str,
    role: str,
    conditions: str = "",
) -> Optional[User]:
    with get_session() as s:
        if s.query(User).filter(
            (User.username == username) | (User.email == email)
        ).first():
            return None          # duplicate
        user = User(
            username=username,
            full_name=full_name,
            email=email,
            password_hash=hash_password(password),
            role=UserRole(role),
            conditions=conditions,
        )
        s.add(user)
        s.flush()
        s.refresh(user)
        s.expunge(user)
        return user


def authenticate_user(username: str, password: str) -> Optional[User]:
    with get_session() as s:
        user = s.query(User).filter_by(username=username, is_active=True).first()
        if user and verify_password(password, user.password_hash):
            s.expunge(user)
            return user
    return None


def get_user_by_id(user_id: int) -> Optional[User]:
    with get_session() as s:
        user = s.query(User).filter_by(id=user_id).first()
        if user:
            s.expunge(user)
        return user


def get_all_patients() -> list[User]:
    with get_session() as s:
        patients = s.query(User).filter_by(role=UserRole.patient, is_active=True).all()
        for p in patients:
            s.expunge(p)
        return patients


def get_assigned_patients(caregiver_id: int) -> list[User]:
    with get_session() as s:
        assignments = (
            s.query(PatientAssignment)
            .filter_by(caregiver_id=caregiver_id)
            .all()
        )
        patient_ids = [a.patient_id for a in assignments]
        patients = s.query(User).filter(User.id.in_(patient_ids)).all()
        for p in patients:
            s.expunge(p)
        return patients


def assign_patient(caregiver_id: int, patient_id: int) -> bool:
    with get_session() as s:
        exists = s.query(PatientAssignment).filter_by(
            caregiver_id=caregiver_id, patient_id=patient_id
        ).first()
        if exists:
            return False
        s.add(PatientAssignment(caregiver_id=caregiver_id, patient_id=patient_id))
    return True


def assign_patients_bulk(caregiver_id: int, patient_ids: list[int]) -> dict:
    """Assign multiple patients at once. Returns {assigned: n, skipped: n}."""
    assigned = 0
    skipped = 0
    for pid in patient_ids:
        ok = assign_patient(caregiver_id, pid)
        if ok:
            assigned += 1
        else:
            skipped += 1
    return {"assigned": assigned, "skipped": skipped}


def unassign_patient(caregiver_id: int, patient_id: int) -> None:
    with get_session() as s:
        row = s.query(PatientAssignment).filter_by(
            caregiver_id=caregiver_id, patient_id=patient_id
        ).first()
        if row:
            s.delete(row)


def update_user_conditions(user_id: int, conditions: str) -> None:
    with get_session() as s:
        user = s.query(User).filter_by(id=user_id).first()
        if user:
            user.conditions = conditions


def update_alert_threshold(user_id: int, threshold: float) -> None:
    with get_session() as s:
        user = s.query(User).filter_by(id=user_id).first()
        if user:
            user.alert_threshold = threshold


def get_patients_below_threshold(caregiver_id: int, days: int = 7) -> list[dict]:
    """Return assigned patients whose adherence is below their own threshold."""
    patients = get_assigned_patients(caregiver_id)
    alerts = []
    for p in patients:
        threshold = p.alert_threshold if p.alert_threshold is not None else 75.0
        stats = get_adherence_stats(p.id, days=days)
        if stats["total"] > 0 and stats["rate"] < threshold:
            alerts.append({
                "patient": p,
                "rate": stats["rate"],
                "threshold": threshold,
                "missed": stats["missed"],
                "total": stats["total"],
                "days": days,
            })
    return alerts


# ══════════════════════════════════════════════════════════════════════════════
# MEDICATION OPERATIONS
# ══════════════════════════════════════════════════════════════════════════════

def add_medication(
    patient_id: int,
    name: str,
    dosage: str,
    frequency: str,
    scheduled_times: list[str],
    condition_tag: str = "",
    instructions: str = "",
    start_date: Optional[datetime] = None,
    end_date: Optional[datetime] = None,
) -> Medication:
    with get_session() as s:
        med = Medication(
            patient_id=patient_id,
            name=name,
            dosage=dosage,
            frequency=frequency,
            scheduled_times=json.dumps(scheduled_times),
            condition_tag=condition_tag,
            instructions=instructions,
            start_date=start_date or _utcnow(),
            end_date=end_date,
        )
        s.add(med)
        s.flush()
        s.refresh(med)
        s.expunge(med)
        return med


def update_medication(
    med_id: int,
    name: str,
    dosage: str,
    frequency: str,
    scheduled_times: list[str],
    condition_tag: str = "",
    instructions: str = "",
    end_date=None,
) -> bool:
    """Update editable fields of an existing medication. Returns True on success."""
    with get_session() as s:
        med = s.query(Medication).filter_by(id=med_id).first()
        if not med:
            return False
        med.name = name
        med.dosage = dosage
        med.frequency = frequency
        med.scheduled_times = json.dumps(scheduled_times)
        med.condition_tag = condition_tag
        med.instructions = instructions
        if end_date is not None:
            med.end_date = end_date
    return True


def get_medications(patient_id: int, active_only: bool = True) -> list[Medication]:
    with get_session() as s:
        q = s.query(Medication).filter_by(patient_id=patient_id)
        if active_only:
            q = q.filter_by(is_active=True)
        meds = q.order_by(Medication.created_at.desc()).all()
        for m in meds:
            s.expunge(m)
        return meds


def deactivate_medication(med_id: int) -> None:
    with get_session() as s:
        med = s.query(Medication).filter_by(id=med_id).first()
        if med:
            med.is_active = False


def get_medication_by_id(med_id: int) -> Optional[Medication]:
    with get_session() as s:
        med = s.query(Medication).filter_by(id=med_id).first()
        if med:
            s.expunge(med)
        return med


# ══════════════════════════════════════════════════════════════════════════════
# MEDICATION LOG OPERATIONS
# ══════════════════════════════════════════════════════════════════════════════

def log_medication(
    patient_id: int,
    medication_id: int,
    scheduled_time: datetime,
    status: str,
    taken_time: Optional[datetime] = None,
    notes: str = "",
    side_effects: str = "",
) -> MedicationLog:
    with get_session() as s:
        log = MedicationLog(
            patient_id=patient_id,
            medication_id=medication_id,
            scheduled_time=scheduled_time,
            taken_time=taken_time or (_utcnow() if status == "taken" else None),
            status=status,
            notes=notes,
            side_effects=side_effects,
        )
        s.add(log)
        s.flush()
        s.refresh(log)
        s.expunge(log)
        return log


def get_logs_for_patient(
    patient_id: int,
    days: int = 30,
) -> list[MedicationLog]:
    since = _utcnow() - timedelta(days=days)
    with get_session() as s:
        logs = (
            s.query(MedicationLog)
            .filter(
                MedicationLog.patient_id == patient_id,
                MedicationLog.scheduled_time >= since,
            )
            .order_by(MedicationLog.scheduled_time.desc())
            .all()
        )
        for lg in logs:
            s.expunge(lg)
        return logs


def get_today_logs(patient_id: int) -> list[MedicationLog]:
    today_start = _utcnow().replace(hour=0, minute=0, second=0, microsecond=0)
    today_end = today_start + timedelta(days=1)
    with get_session() as s:
        logs = (
            s.query(MedicationLog)
            .filter(
                MedicationLog.patient_id == patient_id,
                MedicationLog.scheduled_time >= today_start,
                MedicationLog.scheduled_time < today_end,
            )
            .all()
        )
        for lg in logs:
            s.expunge(lg)
        return logs


def get_adherence_stats(patient_id: int, days: int = 30) -> dict:
    logs = get_logs_for_patient(patient_id, days)
    total = len(logs)
    if total == 0:
        return {"total": 0, "taken": 0, "missed": 0, "skipped": 0, "rate": 0.0}
    taken = sum(1 for l in logs if l.status == "taken")
    missed = sum(1 for l in logs if l.status == "missed")
    skipped = sum(1 for l in logs if l.status == "skipped")
    return {
        "total": total,
        "taken": taken,
        "missed": missed,
        "skipped": skipped,
        "rate": round((taken / total) * 100, 1),
    }


# ══════════════════════════════════════════════════════════════════════════════
# REMINDER OPERATIONS
# ══════════════════════════════════════════════════════════════════════════════

def create_reminder(
    patient_id: int,
    medication_id: int,
    reminder_time: datetime,
    minutes_before: int,
    message: str,
) -> Reminder:
    with get_session() as s:
        r = Reminder(
            patient_id=patient_id,
            medication_id=medication_id,
            reminder_time=reminder_time,
            minutes_before=minutes_before,
            message=message,
        )
        s.add(r)
        s.flush()
        s.refresh(r)
        s.expunge(r)
        return r


def get_pending_reminders(patient_id: int) -> list[Reminder]:
    now = _utcnow()
    window = now + timedelta(hours=2)
    with get_session() as s:
        reminders = (
            s.query(Reminder)
            .filter(
                Reminder.patient_id == patient_id,
                Reminder.is_dismissed == False,
                Reminder.reminder_time <= window,
                Reminder.reminder_time >= now - timedelta(hours=1),
            )
            .order_by(Reminder.reminder_time.asc())
            .all()
        )
        for r in reminders:
            s.expunge(r)
        return reminders


def get_all_reminders(patient_id: int) -> list[Reminder]:
    with get_session() as s:
        reminders = (
            s.query(Reminder)
            .filter_by(patient_id=patient_id, is_dismissed=False)
            .order_by(Reminder.reminder_time.asc())
            .all()
        )
        for r in reminders:
            s.expunge(r)
        return reminders


def dismiss_reminder(reminder_id: int) -> None:
    with get_session() as s:
        r = s.query(Reminder).filter_by(id=reminder_id).first()
        if r:
            r.is_dismissed = True


# ══════════════════════════════════════════════════════════════════════════════
# AI CONVERSATION HISTORY
# ══════════════════════════════════════════════════════════════════════════════

def save_ai_message(user_id: int, role: str, content: str) -> None:
    with get_session() as s:
        s.add(AIConversation(user_id=user_id, role=role, content=content))


def get_ai_history(user_id: int, limit: int = 20) -> list[AIConversation]:
    with get_session() as s:
        rows = (
            s.query(AIConversation)
            .filter_by(user_id=user_id)
            .order_by(AIConversation.created_at.asc())
            .limit(limit)
            .all()
        )
        for r in rows:
            s.expunge(r)
        return rows


def clear_ai_history(user_id: int) -> None:
    with get_session() as s:
        s.query(AIConversation).filter_by(user_id=user_id).delete()


# ══════════════════════════════════════════════════════════════════════════════
# TREND / CHART DATA HELPERS
# ══════════════════════════════════════════════════════════════════════════════

def get_weekly_adherence(patient_id: int, weeks: int = 12) -> list[dict]:
    """Return per-week adherence rate for the last N weeks."""
    rows = []
    for w in range(weeks - 1, -1, -1):
        week_end = _utcnow() - timedelta(weeks=w)
        week_start = week_end - timedelta(weeks=1)
        with get_session() as s:
            logs = (
                s.query(MedicationLog)
                .filter(
                    MedicationLog.patient_id == patient_id,
                    MedicationLog.scheduled_time >= week_start,
                    MedicationLog.scheduled_time < week_end,
                )
                .all()
            )
            statuses = [lg.status for lg in logs]
        total = len(statuses)
        taken = sum(1 for st in statuses if st == "taken")
        rate = round((taken / total) * 100, 1) if total > 0 else None
        rows.append({
            "week": week_end.strftime("W%V %b %d"),
            "total": total,
            "taken": taken,
            "rate": rate,
        })
    return rows


def get_monthly_adherence(patient_id: int, months: int = 6) -> list[dict]:
    """Return per-month adherence rate for the last N months."""
    from dateutil.relativedelta import relativedelta
    rows = []
    now = _utcnow()
    for m in range(months - 1, -1, -1):
        month_end = now - relativedelta(months=m)
        month_start = month_end - relativedelta(months=1)
        with get_session() as s:
            logs = (
                s.query(MedicationLog)
                .filter(
                    MedicationLog.patient_id == patient_id,
                    MedicationLog.scheduled_time >= month_start,
                    MedicationLog.scheduled_time < month_end,
                )
                .all()
            )
            statuses = [lg.status for lg in logs]
        total = len(statuses)
        taken = sum(1 for st in statuses if st == "taken")
        rate = round((taken / total) * 100, 1) if total > 0 else None
        rows.append({
            "month": month_end.strftime("%b %Y"),
            "total": total,
            "taken": taken,
            "rate": rate,
        })
    return rows


def get_existing_log(patient_id: int, medication_id: int, scheduled_time: datetime) -> Optional[MedicationLog]:
    """Check if a log already exists for this slot (prevents duplicates)."""
    window_start = scheduled_time - timedelta(minutes=30)
    window_end = scheduled_time + timedelta(minutes=30)
    with get_session() as s:
        log = (
            s.query(MedicationLog)
            .filter(
                MedicationLog.patient_id == patient_id,
                MedicationLog.medication_id == medication_id,
                MedicationLog.scheduled_time >= window_start,
                MedicationLog.scheduled_time <= window_end,
            )
            .first()
        )
        if log:
            s.expunge(log)
        return log


# ══════════════════════════════════════════════════════════════════════════════
# CAREGIVER PATIENT NOTES (per caregiver-patient pair)
# ══════════════════════════════════════════════════════════════════════════════

def get_caregiver_note(caregiver_id: int, patient_id: int) -> Optional[CaregiverPatientNote]:
    """Return the caregiver's note record for a patient, or None if not yet created."""
    with get_session() as s:
        row = s.query(CaregiverPatientNote).filter_by(
            caregiver_id=caregiver_id, patient_id=patient_id
        ).first()
        if row:
            s.expunge(row)
        return row


def upsert_caregiver_note(
    caregiver_id: int,
    patient_id: int,
    conditions: str = "",
    allergies: str = "",
    emergency_name: str = "",
    emergency_phone: str = "",
    blood_type: str = "",
    weight_kg: Optional[float] = None,
    height_cm: Optional[float] = None,
    care_plan: str = "",
    clinical_notes: str = "",
    diet_notes: str = "",
    exercise_notes: str = "",
    medication_notes: str = "[]",
) -> CaregiverPatientNote:
    """Create or fully update the caregiver note for a patient."""
    with get_session() as s:
        row = s.query(CaregiverPatientNote).filter_by(
            caregiver_id=caregiver_id, patient_id=patient_id
        ).first()
        if row is None:
            row = CaregiverPatientNote(
                caregiver_id=caregiver_id,
                patient_id=patient_id,
            )
            s.add(row)
        row.conditions      = conditions
        row.allergies       = allergies
        row.emergency_name  = emergency_name
        row.emergency_phone = emergency_phone
        row.blood_type      = blood_type
        row.weight_kg       = weight_kg
        row.height_cm       = height_cm
        row.care_plan       = care_plan
        row.clinical_notes  = clinical_notes
        row.diet_notes      = diet_notes
        row.exercise_notes  = exercise_notes
        row.medication_notes = medication_notes
        row.updated_at      = _utcnow()
        s.flush()
        s.refresh(row)
        s.expunge(row)
        return row
