"""
app.py — MedAdhere AI · Main Streamlit application entry point
Run with:  streamlit run app.py
"""

from __future__ import annotations

import streamlit as st

# ── Page config must be the very first Streamlit call ─────────────────────────
st.set_page_config(
    page_title="MedAdhere AI",
    page_icon="💊",
    layout="wide",
    initial_sidebar_state="expanded",
)

# ── Local imports (after page config) ────────────────────────────────────────
from config import APP_NAME, APP_TAGLINE, ROLE_PATIENT, ROLE_CAREGIVER, ROLE_DOCTOR
from database.db_manager import init_db
from modules.auth import is_logged_in, render_auth_page
from pages import patient_dashboard, caregiver_dashboard, doctor_dashboard


# ── Database initialisation ───────────────────────────────────────────────────

@st.cache_resource
def initialise_database():
    init_db()
    return True


initialise_database()


# ── Global styles ─────────────────────────────────────────────────────────────

def apply_global_styles() -> None:
    st.markdown(
        """
        <style>
        /* Tighten sidebar width */
        [data-testid="stSidebar"] { min-width: 220px; max-width: 240px; }
        /* Metric card padding */
        [data-testid="stMetric"] { background: #f7f8fa; border-radius: 8px; padding: 12px; }
        /* Remove top padding on main area */
        .main .block-container { padding-top: 1.5rem; }
        </style>
        """,
        unsafe_allow_html=True,
    )


apply_global_styles()


# ══════════════════════════════════════════════════════════════════════════════
# MAIN ROUTING
# ══════════════════════════════════════════════════════════════════════════════

def main() -> None:
    if not is_logged_in():
        render_auth_page()
        return

    user = st.session_state["user"]
    role = user.role.value if hasattr(user.role, "value") else str(user.role)

    if role == ROLE_PATIENT:
        patient_dashboard.render(user)
    elif role in (ROLE_CAREGIVER, ROLE_DOCTOR):
        # Doctors get the richer doctor dashboard; caregivers get the caregiver one
        if role == ROLE_DOCTOR:
            doctor_dashboard.render(user)
        else:
            caregiver_dashboard.render(user)
    else:
        st.error(f"Unknown role: {role}. Please contact support.")


if __name__ == "__main__":
    main()
else:
    # Streamlit imports app.py as a module — run main() in both cases
    main()
