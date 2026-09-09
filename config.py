"""
config.py — Application-wide constants and configuration
"""

import os
from dotenv import load_dotenv

load_dotenv()


def _get_gemini_key() -> str:
    """Read API key from .env first, then fall back to Streamlit secrets."""
    key = os.getenv("GEMINI_API_KEY", "")
    if not key:
        try:
            import streamlit as st
            key = st.secrets.get("GEMINI_API_KEY", "")
        except Exception:
            pass
    return key


# ── Gemini ────────────────────────────────────────────────────────────────────
GEMINI_API_KEY: str = _get_gemini_key()
GEMINI_MODEL: str = "gemini-2.5-flash"

# ── Database ──────────────────────────────────────────────────────────────────
DATABASE_URL: str = os.getenv("DATABASE_URL", "sqlite:///medication_tracker.db")

# ── App meta ──────────────────────────────────────────────────────────────────
APP_NAME: str = "MedAdhere AI"
APP_TAGLINE: str = "AI-Powered Medication Adherence Tracker for Chronic Patients"

# ── User roles ────────────────────────────────────────────────────────────────
ROLE_PATIENT: str = "patient"
ROLE_CAREGIVER: str = "caregiver"
ROLE_DOCTOR: str = "doctor"
ALL_ROLES: list[str] = [ROLE_PATIENT, ROLE_CAREGIVER, ROLE_DOCTOR]

# ── Medication frequency options ──────────────────────────────────────────────
FREQUENCY_OPTIONS: list[str] = [
    "Once daily",
    "Twice daily",
    "Three times daily",
    "Four times daily",
    "Every 4 hours",
    "Every 6 hours",
    "Every 8 hours",
    "Every 12 hours",
    "Weekly",
    "As needed",
]

# ── Adherence thresholds (%) ──────────────────────────────────────────────────
ADHERENCE_EXCELLENT: int = 90
ADHERENCE_GOOD: int = 75
ADHERENCE_FAIR: int = 50

# ── Chronic conditions (used as tags) ────────────────────────────────────────
CHRONIC_CONDITIONS: list[str] = [
    "Diabetes",
    "Hypertension",
    "Heart Disease",
    "Asthma / COPD",
    "Arthritis",
    "Chronic Kidney Disease",
    "Epilepsy",
    "Depression / Anxiety",
    "Hypothyroidism",
    "HIV/AIDS",
    "Cancer",
    "Other",
]

# ── Reminder windows (minutes before scheduled time) ─────────────────────────
REMINDER_WINDOWS: list[int] = [5, 10, 15, 30, 60]
