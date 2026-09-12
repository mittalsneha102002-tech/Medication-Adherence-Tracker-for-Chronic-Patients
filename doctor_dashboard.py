"""
pages/doctor_dashboard.py — Doctor clinical dashboard
Doctors have access to all patients + full clinical summaries + AI tools.
"""

from __future__ import annotations

import pandas as pd
import streamlit as st

from modules import auth, analytics, ai_engine
from database import db_manager as db


def render(user) -> None:
    with st.sidebar:
        st.markdown(f"### 👨‍⚕️ Dr. {user.full_name}")
        st.caption("Role: Doctor")
        st.divider()

        page = st.radio(
            "Navigation",
            options=[
                "Population Overview",
                "Patient Detail",
                "My Patients",
                "Assign Patients",
                "AI Clinical Tools",
            ],
            label_visibility="collapsed",
        )

        st.divider()
        if st.button("🚪 Logout", use_container_width=True):
            auth.logout()

    if page == "Population Overview":
        _render_population_overview(user)
    elif page == "Patient Detail":
        _render_patient_detail(user)
    elif page == "My Patients":
        _render_my_patients(user)
    elif page == "Assign Patients":
        _render_assign_patients(user)
    elif page == "AI Clinical Tools":
        _render_ai_clinical_tools(user)


# ── Population Overview ────────────────────────────────────────────────────────

def _render_population_overview(user) -> None:
    st.subheader("Population Adherence Overview")

    patients = db.get_assigned_patients(user.id)
    if not patients:
        st.info("No patients assigned. Go to **Assign Patients** to add patients.")
        return

    # Build summary table
    rows = []
    for p in patients:
        stats_7 = db.get_adherence_stats(p.id, days=7)
        stats_30 = db.get_adherence_stats(p.id, days=30)
        meds = db.get_medications(p.id)
        rows.append({
            "Patient": p.full_name,
            "Username": p.username,
            "Conditions": p.conditions or "—",
            "Active Meds": len(meds),
            "7-Day %": stats_7["rate"],
            "30-Day %": stats_30["rate"],
            "Missed (30d)": stats_30["missed"],
            "Status": _adherence_label(stats_30["rate"]),
        })

    df = pd.DataFrame(rows)
    st.dataframe(
        df.style.applymap(
            lambda v: "color: #ef4444" if isinstance(v, (int, float)) and v < 50 else
                      "color: #f59e0b" if isinstance(v, (int, float)) and v < 75 else
                      "color: #22c55e" if isinstance(v, (int, float)) and v >= 90 else "",
            subset=["7-Day %", "30-Day %"],
        ),
        use_container_width=True,
        hide_index=True,
    )

    st.divider()

    # Alert section — patients with poor adherence
    poor = [r for r in rows if r["30-Day %"] < 50]
    if poor:
        st.error(f"⚠️ {len(poor)} patient(s) have critical adherence (<50%) in the last 30 days:")
        for r in poor:
            st.markdown(f"- **{r['Patient']}** — {r['30-Day %']}% ({r['Conditions']})")


def _adherence_label(rate: float) -> str:
    if rate >= 90:
        return "🟢 Excellent"
    if rate >= 75:
        return "🟡 Good"
    if rate >= 50:
        return "🟠 Fair"
    return "🔴 Critical"


# ── Patient Detail ─────────────────────────────────────────────────────────────

def _render_patient_detail(user) -> None:
    st.subheader("Patient Detail View")

    patients = db.get_assigned_patients(user.id)
    if not patients:
        st.info("No patients assigned.")
        return

    patient_options = {p.id: f"{p.full_name} (@{p.username})" for p in patients}
    selected_id = st.selectbox(
        "Select Patient",
        options=list(patient_options.keys()),
        format_func=lambda k: patient_options[k],
    )

    selected_patient = next((p for p in patients if p.id == selected_id), None)
    if not selected_patient:
        return

    period = st.selectbox(
        "Period", [7, 14, 30, 60], index=2,
        format_func=lambda d: f"Last {d} days",
    )

    analytics.render_doctor_summary(selected_patient, days=period)

    # Medication list
    st.divider()
    st.markdown("#### Active Medications")
    meds = db.get_medications(selected_patient.id)
    if meds:
        for m in meds:
            import json
            times = json.loads(m.scheduled_times or "[]")
            st.markdown(
                f"- **{m.name}** {m.dosage} · {m.frequency} · "
                f"Times: {', '.join(times) or 'Not set'}"
            )
    else:
        st.info("No active medications.")


# ── My Patients ────────────────────────────────────────────────────────────────

def _render_my_patients(user) -> None:
    st.subheader("My Patient List")

    patients = db.get_assigned_patients(user.id)
    if not patients:
        st.info("No patients assigned yet.")
        return

    for patient in patients:
        stats = db.get_adherence_stats(patient.id, days=30)
        meds = db.get_medications(patient.id)

        with st.container(border=True):
            col1, col2, col3 = st.columns([3, 2, 1])
            with col1:
                st.markdown(f"**{patient.full_name}** (@{patient.username})")
                st.caption(patient.conditions or "No conditions listed")
                st.caption(f"Active medications: {len(meds)}")
            with col2:
                st.metric("30-Day Adherence", f"{stats['rate']}%")
            with col3:
                st.markdown(_adherence_label(stats["rate"]))


# ── Assign Patients ────────────────────────────────────────────────────────────

def _render_assign_patients(user) -> None:
    st.subheader("Manage Patient Assignments")

    all_patients = db.get_all_patients()
    assigned = db.get_assigned_patients(user.id)
    assigned_ids = {p.id for p in assigned}
    unassigned = [p for p in all_patients if p.id not in assigned_ids]

    col1, col2 = st.columns(2)

    with col1:
        st.markdown("#### Assign Patient")
        if not unassigned:
            st.info("All registered patients are already assigned.")
        else:
            options = {p.id: f"{p.full_name} (@{p.username})" for p in unassigned}
            with st.form("doc_assign_form", clear_on_submit=True):
                pid = st.selectbox(
                    "Patient",
                    options=list(options.keys()),
                    format_func=lambda k: options[k],
                )
                if st.form_submit_button("Assign", use_container_width=True):
                    db.assign_patient(user.id, pid)
                    st.success("Patient assigned!")
                    st.rerun()

    with col2:
        st.markdown("#### Remove Assignment")
        if not assigned:
            st.info("No patients assigned.")
        else:
            options = {p.id: f"{p.full_name} (@{p.username})" for p in assigned}
            with st.form("doc_unassign_form", clear_on_submit=True):
                pid = st.selectbox(
                    "Patient",
                    options=list(options.keys()),
                    format_func=lambda k: options[k],
                )
                if st.form_submit_button("Remove", use_container_width=True):
                    db.unassign_patient(user.id, pid)
                    st.success("Removed.")
                    st.rerun()


# ── AI Clinical Tools ──────────────────────────────────────────────────────────

def _render_ai_clinical_tools(user) -> None:
    st.subheader("AI Clinical Tools")
    st.caption("AI-powered clinical decision support for medication adherence management")

    patients = db.get_assigned_patients(user.id)
    if not patients:
        st.info("Assign patients to access AI clinical tools.")
        return

    patient_options = {p.id: p.full_name for p in patients}
    selected_id = st.selectbox(
        "Select Patient",
        options=list(patient_options.keys()),
        format_func=lambda k: patient_options[k],
    )

    selected_patient = next((p for p in patients if p.id == selected_id), None)
    if not selected_patient:
        return

    period = st.selectbox(
        "Analysis Period", [7, 14, 30, 60], index=2,
        format_func=lambda d: f"Last {d} days",
    )

    st.divider()

    tab1, tab2, tab3 = st.tabs([
        "Clinical Summary", "Adherence Analysis", "Improvement Plan"
    ])

    with tab1:
        st.markdown("Generate a complete clinical summary for physician review.")
        if st.button("Generate Clinical Summary", use_container_width=True, key="doc_clin_sum"):
            stats = db.get_adherence_stats(selected_patient.id, days=period)
            stats["days"] = period
            logs = db.get_logs_for_patient(selected_patient.id, days=period)
            meds = db.get_medications(selected_patient.id)
            side_effects = list({
                lg.side_effects for lg in logs
                if lg.side_effects and lg.side_effects.strip()
            })
            med_dicts = [
                {"name": m.name, "dosage": m.dosage, "frequency": m.frequency}
                for m in meds
            ]
            with st.spinner("Generating clinical summary..."):
                summary = ai_engine.summarise_patient_for_doctor(
                    patient_name=selected_patient.full_name,
                    conditions=selected_patient.conditions or "Not specified",
                    medications=med_dicts,
                    stats=stats,
                    recent_side_effects=side_effects,
                )
            st.markdown(summary)

    with tab2:
        st.markdown("Analyse adherence patterns and identify risk factors.")
        if st.button("Analyse Adherence", use_container_width=True, key="doc_adh_anal"):
            stats = db.get_adherence_stats(selected_patient.id, days=period)
            stats["days"] = period
            with st.spinner("Analysing adherence patterns..."):
                analysis = ai_engine.analyse_adherence(
                    patient_name=selected_patient.full_name,
                    stats=stats,
                    conditions=selected_patient.conditions or "Not specified",
                )
            st.markdown(analysis)

    with tab3:
        st.markdown("Create a personalised adherence improvement plan.")
        barriers = st.text_area(
            "Known barriers to adherence (optional)",
            placeholder="e.g. forgetfulness, side effects, cost, complexity of regimen...",
            height=80,
        )
        if st.button("Generate Improvement Plan", use_container_width=True, key="doc_imp_plan"):
            meds = db.get_medications(selected_patient.id)
            med_dicts = [{"name": m.name} for m in meds]
            with st.spinner("Creating personalised plan..."):
                plan = ai_engine.suggest_adherence_improvements(
                    conditions=selected_patient.conditions or "chronic condition",
                    medications=med_dicts,
                    barriers=barriers,
                )
            st.markdown(plan)
