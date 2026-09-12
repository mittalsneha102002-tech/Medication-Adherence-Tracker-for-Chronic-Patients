"""
pages/caregiver_dashboard.py — Caregiver monitoring dashboard
Features: linked patient monitoring, automated low-adherence alerts,
          per-patient trend charts, alert threshold configuration.
"""

from __future__ import annotations

import pandas as pd
import streamlit as st

from modules import auth, analytics, ai_engine
from database import db_manager as db
from config import ROLE_CAREGIVER, ROLE_DOCTOR


def render(user) -> None:
    role_label = "Caregiver" if user.role.value == ROLE_CAREGIVER else "Doctor"

    # ── Auto-check alerts on every load ──────────────────────────────────────
    _render_alert_banner(user)

    with st.sidebar:
        st.markdown(f"### 🩺 {user.full_name}")
        st.caption(f"Role: {role_label}")
        st.divider()

        page = st.radio(
            "Navigation",
            options=["🏠 Overview", "👥 My Patients", "📋 Patient Detail",
                     "🔗 Assign Patients", "🤖 AI Insights"],
            label_visibility="collapsed",
        )

        st.divider()
        if st.button("🚪 Logout", use_container_width=True):
            auth.logout()

    page_key = page.split(" ", 1)[1]   # strip emoji prefix

    if page_key == "Overview":
        _render_overview(user)
    elif page_key == "My Patients":
        _render_my_patients(user)
    elif page_key == "Patient Detail":
        _render_patient_detail(user)
    elif page_key == "Assign Patients":
        _render_assign_patients(user)
    elif page_key == "AI Insights":
        _render_ai_insights(user)


# ── Alert banner ──────────────────────────────────────────────────────────────

def _render_alert_banner(user) -> None:
    """Check all assigned patients and surface low-adherence alerts."""
    alerts = db.get_patients_below_threshold(user.id, days=7)
    if not alerts:
        return

    st.error(
        f"🚨 **{len(alerts)} patient(s) have low adherence (7-day)** — "
        "immediate attention recommended."
    )
    for a in alerts:
        p = a["patient"]
        col1, col2 = st.columns([5, 1])
        with col1:
            st.warning(
                f"⚠️ **{p.full_name}** — {a['rate']}% adherence "
                f"(threshold: {a['threshold']}%)  |  "
                f"{a['missed']} missed / {a['total']} doses in 7 days"
            )
        with col2:
            if st.button("View", key=f"alert_view_{p.id}"):
                st.session_state["alert_patient_id"] = p.id
    st.divider()


# ── Overview ──────────────────────────────────────────────────────────────────

def _render_overview(user) -> None:
    st.subheader("📊 Patient Adherence Overview")

    patients = db.get_assigned_patients(user.id)
    if not patients:
        st.info("No patients assigned yet. Go to **Assign Patients** to add patients.")
        return

    # Summary metric cards
    cols = st.columns(min(len(patients), 4))
    for i, patient in enumerate(patients):
        stats7 = db.get_adherence_stats(patient.id, days=7)
        rate = stats7["rate"]
        threshold = float(getattr(patient, "alert_threshold", 75) or 75)
        color = "🟢" if rate >= 90 else ("🟡" if rate >= 75 else ("🟠" if rate >= 50 else "🔴"))
        alert_flag = " 🚨" if rate < threshold and stats7["total"] > 0 else ""

        with cols[i % 4]:
            with st.container(border=True):
                st.markdown(f"**{patient.full_name}**{alert_flag}")
                st.markdown(f"{color} {rate}% *(7-day)*")
                st.caption(patient.conditions or "No conditions listed")
                meds_count = len(db.get_medications(patient.id))
                st.caption(f"{meds_count} active medication(s)")

    st.divider()

    # Summary table
    rows = []
    for p in patients:
        s7  = db.get_adherence_stats(p.id, days=7)
        s30 = db.get_adherence_stats(p.id, days=30)
        threshold = float(getattr(p, "alert_threshold", 75) or 75)
        rows.append({
            "Patient": p.full_name,
            "Conditions": p.conditions or "—",
            "Active Meds": len(db.get_medications(p.id)),
            "7-Day %": s7["rate"],
            "30-Day %": s30["rate"],
            "Threshold": f"{threshold}%",
            "Status": "🚨 Alert" if s7["rate"] < threshold and s7["total"] > 0
                      else ("🟢 Good" if s7["rate"] >= 75 else "🟡 Watch"),
        })

    df = pd.DataFrame(rows)
    st.dataframe(df, use_container_width=True, hide_index=True)


# ── My Patients ────────────────────────────────────────────────────────────────

def _render_my_patients(user) -> None:
    st.subheader("👥 My Patients")

    patients = db.get_assigned_patients(user.id)
    if not patients:
        st.info("No patients assigned yet.")
        return

    for patient in patients:
        stats = db.get_adherence_stats(patient.id, days=30)
        meds = db.get_medications(patient.id)
        threshold = float(getattr(patient, "alert_threshold", 75) or 75)
        alert = stats["rate"] < threshold and stats["total"] > 0

        with st.container(border=True):
            col1, col2, col3 = st.columns([3, 2, 2])
            with col1:
                st.markdown(f"**{patient.full_name}** (@{patient.username})")
                st.caption(patient.conditions or "No conditions listed")
                st.caption(f"{len(meds)} active medication(s)")
            with col2:
                st.metric("30-Day Adherence", f"{stats['rate']}%",
                          f"threshold {threshold}%",
                          delta_color="normal" if not alert else "inverse")
            with col3:
                if alert:
                    st.error("🚨 Below Threshold")
                elif stats["rate"] >= 90:
                    st.success("🟢 Excellent")
                elif stats["rate"] >= 75:
                    st.success("🟡 Good")
                else:
                    st.warning("🟠 Fair")


# ── Patient Detail ─────────────────────────────────────────────────────────────

def _render_patient_detail(user) -> None:
    st.subheader("📋 Patient Detail")

    patients = db.get_assigned_patients(user.id)
    if not patients:
        st.info("No patients assigned.")
        return

    # Pre-select from alert banner click
    default_id = st.session_state.pop("alert_patient_id", None)
    patient_options = {p.id: f"{p.full_name} (@{p.username})" for p in patients}
    default_idx = list(patient_options.keys()).index(default_id) \
        if default_id and default_id in patient_options else 0

    selected_id = st.selectbox(
        "Select Patient",
        options=list(patient_options.keys()),
        format_func=lambda k: patient_options[k],
        index=default_idx,
    )
    selected_patient = next((p for p in patients if p.id == selected_id), None)
    if not selected_patient:
        return

    # Tabs: Analytics | Edit Patient Details | Medications | Logs
    tab_analytics, tab_profile, tab_meds, tab_logs = st.tabs([
        "📊 Analytics",
        "✏️ Edit Patient Details",
        "💊 Medications",
        "📋 Recent Logs",
    ])

    with tab_analytics:
        period = st.selectbox("Period", [7, 14, 30, 60], index=2,
                              format_func=lambda d: f"Last {d} days",
                              key="cg_detail_period")
        analytics.render_caregiver_analytics(selected_patient, days=period)

    with tab_profile:
        _render_patient_profile_editor(user, selected_patient)

    with tab_meds:
        _render_patient_medication_editor(user, selected_patient)

    with tab_logs:
        _render_patient_logs(user, selected_patient)


def _render_patient_profile_editor(caregiver, patient) -> None:
    """Full caregiver-editable patient profile panel."""
    from config import CHRONIC_CONDITIONS

    # Load existing caregiver note (or blank defaults)
    note = db.get_caregiver_note(caregiver.id, patient.id)

    st.markdown(f"### 🧑‍⚕️ Patient Profile — {patient.full_name}")
    st.caption(
        f"These details are maintained by you ({caregiver.full_name}) and are "
        "visible only to caregivers/doctors assigned to this patient."
    )
    if note and note.updated_at:
        st.caption(f"Last updated: {note.updated_at.strftime('%b %d, %Y at %H:%M')}")

    # ── Section 1: Basic Info ──────────────────────────────────────────────────
    st.markdown("#### 👤 Basic Information")
    with st.form(f"profile_basic_{patient.id}", clear_on_submit=False):
        col1, col2, col3 = st.columns(3)
        with col1:
            blood_type = st.selectbox(
                "Blood Type",
                ["", "A+", "A−", "B+", "B−", "AB+", "AB−", "O+", "O−", "Unknown"],
                index=(["", "A+", "A−", "B+", "B−", "AB+", "AB−", "O+", "O−", "Unknown"]
                       .index(note.blood_type) if note and note.blood_type in
                       ["", "A+", "A−", "B+", "B−", "AB+", "AB−", "O+", "O−", "Unknown"]
                       else 0),
            )
        with col2:
            weight_kg = st.number_input(
                "Weight (kg)",
                min_value=0.0, max_value=300.0, step=0.5,
                value=float(note.weight_kg) if note and note.weight_kg else 0.0,
            )
        with col3:
            height_cm = st.number_input(
                "Height (cm)",
                min_value=0.0, max_value=250.0, step=0.5,
                value=float(note.height_cm) if note and note.height_cm else 0.0,
            )

        # Chronic conditions — multi-select with pre-filled values
        existing_conds = [c.strip() for c in (note.conditions if note else
                          patient.conditions or "").split(",") if c.strip()]
        conditions = st.multiselect(
            "Chronic Conditions",
            options=CHRONIC_CONDITIONS,
            default=[c for c in existing_conds if c in CHRONIC_CONDITIONS],
        )
        other_condition = st.text_input(
            "Other condition (free text)",
            value=", ".join(c for c in existing_conds if c not in CHRONIC_CONDITIONS),
            placeholder="e.g. Lupus, Psoriasis",
        )

        allergies = st.text_area(
            "Allergies (drug / food / environmental)",
            value=note.allergies if note else "",
            height=70,
            placeholder="e.g. Penicillin, Sulfa drugs, Peanuts",
        )

        st.markdown("#### 🚨 Emergency Contact")
        ec1, ec2 = st.columns(2)
        with ec1:
            emerg_name = st.text_input(
                "Contact Name",
                value=note.emergency_name if note else "",
                placeholder="e.g. John Doe (Spouse)",
            )
        with ec2:
            emerg_phone = st.text_input(
                "Contact Phone",
                value=note.emergency_phone if note else "",
                placeholder="e.g. +1 555-0100",
            )

        if st.form_submit_button("💾 Save Basic Info", use_container_width=True):
            all_conds = conditions + ([other_condition.strip()] if other_condition.strip() else [])
            _save_caregiver_note(caregiver.id, patient.id, note, {
                "conditions": ", ".join(all_conds),
                "allergies": allergies.strip(),
                "blood_type": blood_type,
                "weight_kg": weight_kg if weight_kg > 0 else None,
                "height_cm": height_cm if height_cm > 0 else None,
                "emergency_name": emerg_name.strip(),
                "emergency_phone": emerg_phone.strip(),
            })
            st.success("✅ Basic information saved.")
            st.rerun()

    # Display BMI if both weight & height are known
    if note and note.weight_kg and note.height_cm and note.height_cm > 0:
        bmi = note.weight_kg / ((note.height_cm / 100) ** 2)
        bmi_label = (
            "Underweight" if bmi < 18.5 else
            "Normal weight" if bmi < 25 else
            "Overweight" if bmi < 30 else "Obese"
        )
        st.info(f"**BMI:** {bmi:.1f} — {bmi_label}")

    st.divider()

    # ── Section 2: Care Plan & Clinical Notes ─────────────────────────────────
    st.markdown("#### 📝 Care Plan & Clinical Notes")
    with st.form(f"profile_notes_{patient.id}", clear_on_submit=False):
        care_plan = st.text_area(
            "Care Plan",
            value=note.care_plan if note else "",
            height=120,
            placeholder=(
                "e.g. Monitor blood glucose twice daily. "
                "Follow diabetic diet. Check HbA1c every 3 months."
            ),
        )
        clinical_notes = st.text_area(
            "Clinical Observations",
            value=note.clinical_notes if note else "",
            height=100,
            placeholder="e.g. Patient reports occasional dizziness. BP slightly elevated on last visit.",
        )
        col_d, col_e = st.columns(2)
        with col_d:
            diet_notes = st.text_area(
                "Dietary Guidance",
                value=note.diet_notes if note else "",
                height=90,
                placeholder="e.g. Low-sodium, low-carb. Avoid alcohol.",
            )
        with col_e:
            exercise_notes = st.text_area(
                "Exercise / Activity Guidance",
                value=note.exercise_notes if note else "",
                height=90,
                placeholder="e.g. 30 min brisk walk daily. Avoid strenuous activity.",
            )

        if st.form_submit_button("💾 Save Notes", use_container_width=True):
            _save_caregiver_note(caregiver.id, patient.id, note, {
                "care_plan": care_plan.strip(),
                "clinical_notes": clinical_notes.strip(),
                "diet_notes": diet_notes.strip(),
                "exercise_notes": exercise_notes.strip(),
            })
            st.success("✅ Care notes saved.")
            st.rerun()


def _save_caregiver_note(caregiver_id: int, patient_id: int,
                         existing, updates: dict) -> None:
    """Helper — merge updates into the existing note (or create fresh)."""
    defaults = {
        "conditions": "", "allergies": "",
        "emergency_name": "", "emergency_phone": "",
        "blood_type": "", "weight_kg": None, "height_cm": None,
        "care_plan": "", "clinical_notes": "",
        "diet_notes": "", "exercise_notes": "",
        "medication_notes": "[]",
    }
    if existing:
        current = {
            "conditions":      existing.conditions or "",
            "allergies":       existing.allergies or "",
            "emergency_name":  existing.emergency_name or "",
            "emergency_phone": existing.emergency_phone or "",
            "blood_type":      existing.blood_type or "",
            "weight_kg":       existing.weight_kg,
            "height_cm":       existing.height_cm,
            "care_plan":       existing.care_plan or "",
            "clinical_notes":  existing.clinical_notes or "",
            "diet_notes":      existing.diet_notes or "",
            "exercise_notes":  existing.exercise_notes or "",
            "medication_notes": existing.medication_notes or "[]",
        }
    else:
        current = defaults.copy()
    current.update(updates)
    db.upsert_caregiver_note(caregiver_id=caregiver_id, patient_id=patient_id, **current)


def _render_patient_medication_editor(caregiver, patient) -> None:
    """Caregiver can add new medications and edit existing ones for the patient."""
    import json
    from config import FREQUENCY_OPTIONS, CHRONIC_CONDITIONS
    from datetime import date, time as dtime, timedelta

    st.markdown(f"### 💊 Medications — {patient.full_name}")
    st.caption("Add new medications or edit existing ones on behalf of this patient.")

    # ── Add new medication ────────────────────────────────────────────────────
    with st.expander("➕ Add New Medication for this Patient", expanded=False):
        with st.form(f"cg_add_med_{patient.id}", clear_on_submit=True):
            col1, col2 = st.columns(2)
            with col1:
                med_name  = st.text_input("Drug Name *", placeholder="e.g. Lisinopril")
                med_dose  = st.text_input("Dosage *", placeholder="e.g. 10 mg")
                frequency = st.selectbox("Frequency *", FREQUENCY_OPTIONS)
                cond_tag  = st.selectbox("Related Condition", [""] + CHRONIC_CONDITIONS)
            with col2:
                start_dt  = st.date_input("Start Date", value=date.today())
                duration  = st.selectbox("Duration", [
                    "7 days","14 days","30 days","60 days","90 days",
                    "6 months","1 year","Ongoing (no end date)"
                ], index=2)
                instruct  = st.text_area("Instructions", height=70,
                                         placeholder="e.g. Take with food")

            _dur_map = {"7 days":7,"14 days":14,"30 days":30,"60 days":60,
                        "90 days":90,"6 months":182,"1 year":365,
                        "Ongoing (no end date)":None}

            st.markdown("**Scheduled Times** (based on frequency)")
            _defaults = {
                "Once daily":["08:00"],"Twice daily":["08:00","20:00"],
                "Three times daily":["08:00","14:00","20:00"],
                "Four times daily":["08:00","12:00","16:00","20:00"],
                "Every 12 hours":["08:00","20:00"],"Every 8 hours":["08:00","16:00","00:00"],
                "Every 6 hours":["06:00","12:00","18:00","00:00"],
                "Weekly":["08:00"],"As needed":[],
            }
            def_times = _defaults.get(frequency, [])
            sched_times: list[str] = []
            if def_times:
                tcols = st.columns(min(len(def_times), 4))
                for i, tc in enumerate(tcols):
                    with tc:
                        h, m = map(int, def_times[i].split(":"))
                        t = st.time_input(f"Time {i+1}", value=dtime(h, m),
                                          key=f"cg_at_{patient.id}_{i}")
                        if t:
                            sched_times.append(t.strftime("%H:%M"))
            else:
                st.info("No fixed times for 'As needed'.")

            if st.form_submit_button("💾 Add Medication", use_container_width=True):
                if not med_name.strip() or not med_dose.strip():
                    st.error("Drug name and dosage are required.")
                else:
                    from datetime import datetime as _dt2
                    dur_days = _dur_map[duration]
                    s_dt = _dt2.combine(start_dt, dtime.min)
                    e_dt = (s_dt + timedelta(days=dur_days)) if dur_days else None
                    db.add_medication(
                        patient_id=patient.id,
                        name=med_name.strip(), dosage=med_dose.strip(),
                        frequency=frequency, scheduled_times=sched_times,
                        condition_tag=cond_tag, instructions=instruct.strip(),
                        start_date=s_dt, end_date=e_dt,
                    )
                    st.success(f"✅ {med_name} added for {patient.full_name}.")
                    st.rerun()

    st.divider()

    # ── Edit existing medications ─────────────────────────────────────────────
    meds = db.get_medications(patient.id)
    if not meds:
        st.info("No active medications for this patient.")
        return

    st.markdown("#### Active Medications")
    for med in meds:
        times = json.loads(med.scheduled_times or "[]")
        times_str = " · ".join(times) if times else "As needed"
        end_str   = med.end_date.strftime("%b %d, %Y") if med.end_date else "Ongoing"

        with st.container(border=True):
            hc1, hc2, hc3 = st.columns([5, 1, 1])
            with hc1:
                st.markdown(f"**💊 {med.name}** &nbsp; `{med.dosage}`")
                st.caption(f"{med.frequency}  ·  {times_str}  ·  Until: {end_str}")
            with hc2:
                ekey = f"cg_edit_{med.id}"
                lbl  = "✏️ Edit" if not st.session_state.get(ekey) else "✖ Cancel"
                if st.button(lbl, key=f"cg_ebtn_{med.id}", use_container_width=True):
                    st.session_state[ekey] = not st.session_state.get(ekey, False)
                    st.rerun()
            with hc3:
                if st.button("🗑️ Del", key=f"cg_del_{med.id}", use_container_width=True):
                    db.deactivate_medication(med.id)
                    st.success(f"{med.name} deactivated.")
                    st.rerun()

            if st.session_state.get(ekey):
                with st.form(f"cg_edit_form_{med.id}", clear_on_submit=False):
                    ec1, ec2 = st.columns(2)
                    with ec1:
                        e_name  = st.text_input("Drug Name", value=med.name)
                        e_dose  = st.text_input("Dosage", value=med.dosage)
                        e_freq  = st.selectbox("Frequency", FREQUENCY_OPTIONS,
                                               index=FREQUENCY_OPTIONS.index(med.frequency)
                                               if med.frequency in FREQUENCY_OPTIONS else 0)
                        e_cond  = st.selectbox("Condition", [""] + CHRONIC_CONDITIONS,
                                               index=([""] + CHRONIC_CONDITIONS).index(med.condition_tag)
                                               if med.condition_tag in CHRONIC_CONDITIONS else 0)
                    with ec2:
                        e_inst  = st.text_area("Instructions", value=med.instructions or "", height=80)
                        e_end   = st.date_input("End Date (optional)",
                                                value=med.end_date.date() if med.end_date else None)

                    st.markdown("**Scheduled Times**")
                    cur_times = times if times else ["08:00"]
                    etcols = st.columns(min(len(cur_times), 4))
                    new_times: list[str] = []
                    for i, etc in enumerate(etcols):
                        with etc:
                            h, m = map(int, cur_times[i].split(":"))
                            et = st.time_input(f"Time {i+1}", value=dtime(h, m),
                                               key=f"cg_et_{med.id}_{i}")
                            if et:
                                new_times.append(et.strftime("%H:%M"))

                    if st.form_submit_button("💾 Save", use_container_width=True):
                        from datetime import datetime as _dt
                        e_end_dt = _dt.combine(e_end, dtime.min) if e_end else None
                        ok = db.update_medication(
                            med.id, e_name.strip(), e_dose.strip(),
                            e_freq, new_times, e_cond, e_inst.strip(), e_end_dt,
                        )
                        if ok:
                            st.session_state[ekey] = False
                            st.success(f"✅ {e_name} updated.")
                            st.rerun()


def _render_patient_logs(caregiver, patient) -> None:
    """Recent medication logs for this patient."""
    period = st.selectbox("Period", [7, 14, 30, 60], index=2,
                          format_func=lambda d: f"Last {d} days",
                          key="cg_logs_period")
    logs = db.get_logs_for_patient(patient.id, days=period)
    if not logs:
        st.info("No logs in selected period.")
        return

    med_names: dict = {}
    rows = []
    for lg in logs:
        if lg.medication_id not in med_names:
            med = db.get_medication_by_id(lg.medication_id)
            med_names[lg.medication_id] = med.name if med else f"#{lg.medication_id}"
        rows.append({
            "Date/Time":  lg.scheduled_time.strftime("%Y-%m-%d %H:%M"),
            "Medication": med_names[lg.medication_id],
            "Status":     lg.status.upper(),
            "Notes":      lg.notes or "",
            "Side Effects": lg.side_effects or "",
        })
    st.dataframe(pd.DataFrame(rows), use_container_width=True, hide_index=True)


# ── Assign Patients ────────────────────────────────────────────────────────────

def _render_assign_patients(user) -> None:
    st.subheader("🔗 Manage Patient Assignments")

    all_patients = db.get_all_patients()
    assigned     = db.get_assigned_patients(user.id)
    assigned_ids = {p.id for p in assigned}
    unassigned   = [p for p in all_patients if p.id not in assigned_ids]

    # ── Assign section ────────────────────────────────────────────────────────
    st.markdown("#### ➕ Assign Patients")

    if not unassigned:
        st.info("All registered patients are already assigned to you.")
    else:
        # Show a summary table of available patients so the user can choose
        # pd is already imported at top of file
        preview_rows = []
        for p in unassigned:
            s = db.get_adherence_stats(p.id, days=30)
            preview_rows.append({
                "Name": p.full_name,
                "Username": f"@{p.username}",
                "Conditions": p.conditions or "—",
                "30-Day Adherence": f"{s['rate']}%" if s["total"] > 0 else "No data",
            })
        st.dataframe(pd.DataFrame(preview_rows), use_container_width=True, hide_index=True)

        # Multi-select — assign one or many at once
        label_map = {p.id: f"{p.full_name}  (@{p.username})" for p in unassigned}
        with st.form("bulk_assign_form", clear_on_submit=True):
            selected_pids = st.multiselect(
                "Select one or more patients to assign",
                options=list(label_map.keys()),
                format_func=lambda k: label_map[k],
            )
            if st.form_submit_button("✅ Assign Selected Patients", use_container_width=True):
                if not selected_pids:
                    st.warning("Select at least one patient.")
                else:
                    result = db.assign_patients_bulk(user.id, selected_pids)
                    st.success(
                        f"✅ {result['assigned']} patient(s) assigned"
                        + (f", {result['skipped']} already assigned." if result['skipped'] else ".")
                    )
                    st.rerun()

    st.divider()

    # ── Remove section ────────────────────────────────────────────────────────
    st.markdown("#### ➖ Remove Assignments")

    if not assigned:
        st.info("No patients assigned yet.")
    else:
        label_map_assigned = {p.id: f"{p.full_name}  (@{p.username})" for p in assigned}
        with st.form("bulk_unassign_form", clear_on_submit=True):
            remove_pids = st.multiselect(
                "Select patients to remove",
                options=list(label_map_assigned.keys()),
                format_func=lambda k: label_map_assigned[k],
            )
            if st.form_submit_button("🗑️ Remove Selected", use_container_width=True):
                if not remove_pids:
                    st.warning("Select at least one patient.")
                else:
                    for pid in remove_pids:
                        db.unassign_patient(user.id, pid)
                    st.success(f"✅ {len(remove_pids)} patient(s) removed.")
                    st.rerun()

    # ── Alert threshold management ────────────────────────────────────────────
    st.divider()
    st.markdown("#### ⚙️ Alert Threshold Settings")
    st.caption("Set the adherence % below which a patient triggers an alert.")

    assigned_fresh = db.get_assigned_patients(user.id)
    if assigned_fresh:
        patient_opts = {p.id: p.full_name for p in assigned_fresh}
        selected_p_id = st.selectbox(
            "Patient",
            options=list(patient_opts.keys()),
            format_func=lambda k: patient_opts[k],
            key="threshold_patient",
        )
        selected_p = next((p for p in assigned_fresh if p.id == selected_p_id), None)
        if selected_p:
            current = float(getattr(selected_p, "alert_threshold", 75) or 75)
            new_threshold = st.slider(
                f"Alert threshold for {selected_p.full_name}",
                min_value=10, max_value=100, value=int(current), step=5,
                format="%d%%",
            )
            if st.button("💾 Save Threshold", use_container_width=True):
                db.update_alert_threshold(selected_p_id, float(new_threshold))
                st.success(
                    f"Alert threshold set to {new_threshold}% for {selected_p.full_name}."
                )
                st.rerun()


# ── AI Insights ────────────────────────────────────────────────────────────────

def _render_ai_insights(user) -> None:
    st.subheader("🤖 AI Patient Insights")
    st.caption("AI-powered adherence analysis and improvement plans.")

    patients = db.get_assigned_patients(user.id)
    if not patients:
        st.info("Assign patients first to access AI insights.")
        return

    patient_options = {p.id: p.full_name for p in patients}
    selected_id = st.selectbox("Select Patient",
                               options=list(patient_options.keys()),
                               format_func=lambda k: patient_options[k])

    selected_patient = next((p for p in patients if p.id == selected_id), None)
    if not selected_patient:
        return

    period = st.selectbox("Analysis Period", [7, 14, 30, 60], index=2,
                          format_func=lambda d: f"Last {d} days",
                          key="cg_ai_period")

    stats = db.get_adherence_stats(selected_patient.id, days=period)
    stats["days"] = period
    meds = db.get_medications(selected_patient.id)
    st.divider()

    col1, col2 = st.columns(2)
    with col1:
        if st.button("📊 Adherence Analysis", use_container_width=True):
            with st.spinner("Analysing adherence..."):
                result = ai_engine.analyse_adherence(
                    patient_name=selected_patient.full_name,
                    stats=stats,
                    conditions=selected_patient.conditions or "Not specified",
                )
            st.markdown(result)

    with col2:
        if user.role.value == ROLE_DOCTOR:
            if st.button("🩺 Clinical Summary", use_container_width=True):
                logs = db.get_logs_for_patient(selected_patient.id, days=period)
                side_effects = list({lg.side_effects for lg in logs
                                     if lg.side_effects and lg.side_effects.strip()})
                med_dicts = [{"name": m.name, "dosage": m.dosage, "frequency": m.frequency}
                             for m in meds]
                with st.spinner("Generating clinical summary..."):
                    summary = ai_engine.summarise_patient_for_doctor(
                        patient_name=selected_patient.full_name,
                        conditions=selected_patient.conditions or "Not specified",
                        medications=med_dicts,
                        stats=stats,
                        recent_side_effects=side_effects,
                    )
                st.markdown(summary)
        else:
            if st.button("💡 Improvement Plan", use_container_width=True):
                med_dicts = [{"name": m.name} for m in meds]
                with st.spinner("Generating improvement plan..."):
                    result = ai_engine.suggest_adherence_improvements(
                        conditions=selected_patient.conditions or "chronic condition",
                        medications=med_dicts, barriers="",
                    )
                st.markdown(result)
