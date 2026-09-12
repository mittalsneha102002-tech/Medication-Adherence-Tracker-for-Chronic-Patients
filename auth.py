"""
modules/auth.py — Login, registration, and session management UI components
"""

from __future__ import annotations

import streamlit as st

from config import ALL_ROLES, CHRONIC_CONDITIONS, ROLE_PATIENT
from database import db_manager as db


# ── Session helpers ───────────────────────────────────────────────────────────

def is_logged_in() -> bool:
    return st.session_state.get("user") is not None


def current_user():
    return st.session_state.get("user")


def logout() -> None:
    for key in ["user", "gemini_model", "chat_history_display"]:
        st.session_state.pop(key, None)
    st.rerun()


# ── Registration form ─────────────────────────────────────────────────────────

def render_register_form() -> None:
    st.subheader("Create Account")

    with st.form("register_form", clear_on_submit=True):
        col1, col2 = st.columns(2)
        with col1:
            full_name = st.text_input("Full Name *")
            username = st.text_input("Username *")
            email = st.text_input("Email *")
        with col2:
            role = st.selectbox("Role *", options=ALL_ROLES,
                                format_func=lambda r: r.capitalize())
            password = st.text_input("Password *", type="password")
            confirm = st.text_input("Confirm Password *", type="password")

        conditions = []
        if role == ROLE_PATIENT:
            conditions = st.multiselect(
                "Chronic Conditions (optional)",
                options=CHRONIC_CONDITIONS,
            )

        submitted = st.form_submit_button("Register", use_container_width=True)

    if submitted:
        errors = []
        if not full_name.strip():
            errors.append("Full name is required.")
        if not username.strip():
            errors.append("Username is required.")
        if not email.strip() or "@" not in email:
            errors.append("A valid email is required.")
        if len(password) < 6:
            errors.append("Password must be at least 6 characters.")
        if password != confirm:
            errors.append("Passwords do not match.")

        if errors:
            for e in errors:
                st.error(e)
            return

        user = db.create_user(
            username=username.strip(),
            full_name=full_name.strip(),
            email=email.strip().lower(),
            password=password,
            role=role,
            conditions=", ".join(conditions),
        )
        if user is None:
            st.error("Username or email already exists. Please choose another.")
        else:
            st.success(f"Account created for {full_name}! You can now log in.")


# ── Login form ────────────────────────────────────────────────────────────────

def render_login_form() -> None:
    st.subheader("Sign In")

    with st.form("login_form"):
        username = st.text_input("Username")
        password = st.text_input("Password", type="password")
        submitted = st.form_submit_button("Login", use_container_width=True)

    if submitted:
        if not username or not password:
            st.error("Please enter both username and password.")
            return
        user = db.authenticate_user(username.strip(), password)
        if user:
            st.session_state["user"] = user
            st.success(f"Welcome back, {user.full_name}!")
            st.rerun()
        else:
            st.error("Invalid username or password.")


# ── Auth gate (renders login/register tabs) ───────────────────────────────────

def render_auth_page() -> None:
    from config import APP_NAME, APP_TAGLINE

    st.markdown(f"## 💊 {APP_NAME}")
    st.markdown(f"*{APP_TAGLINE}*")
    st.divider()

    tab_login, tab_register = st.tabs(["Login", "Create Account"])

    with tab_login:
        render_login_form()

    with tab_register:
        render_register_form()
