"""
modules/medication.py — Medication management UI
Features: full schedule setup (drug, dosage, frequency, duration),
          per-slot daily intake logging (taken / missed / skipped),
          medication info via AI.
"""

from __future__ import annotations

import json
from datetime import datetime, date, time, timedelta, timezone

import streamlit as st

from config import FREQUENCY_OPTIONS, CHRONIC_CONDITIONS, REMINDER_WINDOWS
from database import db_manager as db


def _utcnow() -> datetime:
    return datetime.now(timezone.utc).replace(tzinfo=None)


# ── Default scheduled times per frequency ─────────────────────────────────────
_FREQ_DEFAULT_TIMES: dict[str, list[str]] = {
    "Once daily":        ["08:00"],
    "Twice daily":       ["08:00", "20:00"],
    "Three times daily": ["08:00", "14:00", "20:00"],
    "Four times daily":  ["08:00", "12:00", "16:00", "20:00"],
    "Every 4 hours":     ["06:00", "10:00", "14:00", "18:00", "22:00"],
    "Every 6 hours":     ["06:00", "12:00", "18:00", "00:00"],
    "Every 8 hours":     ["08:00", "16:00", "00:00"],
    "Every 12 hours":    ["08:00", "20:00"],
    "Weekly":            ["08:00"],
    "As needed":         [],
}

_DURATION_OPTIONS: list[str] = [
    "7 days",
    "14 days",
    "30 days",
    "60 days",
    "90 days",
    "6 months",
    "1 year",
    "Ongoing (no end date)",
]

_DURATION_DAYS: dict[str, int | None] = {
    "7 days": 7,
    "14 days": 14,
    "30 days": 30,
    "60 days": 60,
    "90 days": 90,
    "6 months": 182,
    "1 year": 365,
    "Ongoing (no end date)": None,
}


# ══════════════════════════════════════════════════════════════════════════════
# ADD MEDICATION FORM
# ══════════════════════════════════════════════════════════════════════════════

def render_add_medication(patient_id: int) -> None:
    st.subheader("➕ Add New Medication")

    with st.form("add_med_form", clear_on_submit=True):
        st.markdown("**Drug Details**")
        col1, col2 = st.columns(2)
        with col1:
            name = st.text_input("Drug Name *", placeholder="e.g. Metformin")
            dosage = st.text_input("Dosage *", placeholder="e.g. 500 mg")
            condition_tag = st.selectbox("Related Condition", [""] + CHRONIC_CONDITIONS)
        with col2:
            frequency = st.selectbox("Frequency *", FREQUENCY_OPTIONS)
            duration = st.selectbox("Duration *", _DURATION_OPTIONS, index=2)
            start_date = st.date_input("Start Date *", value=date.today())

        st.divider()
        st.markdown("**Scheduled Times**")
        st.caption("Pre-filled based on frequency — adjust as needed.")

        # Pre-fill default times based on chosen frequency
        default_times = _FREQ_DEFAULT_TIMES.get(frequency, [])
        max_slots = max(len(default_times), 1) if frequency != "As needed" else 0

        scheduled_times: list[str] = []
        if max_slots > 0:
            time_cols = st.columns(min(max_slots, 4))
            for i in range(min(max_slots, 4)):
                with time_cols[i]:
                    default_val = None
                    if i < len(default_times):
                        h, m = map(int, default_times[i].split(":"))
                        default_val = time(h, m)
                    t = st.time_input(
                        f"Time {i + 1}",
                        value=default_val,
                        key=f"sched_t_{i}",
                    )
                    if t is not None:
                        scheduled_times.append(t.strftime("%H:%M"))
        else:
            st.info('No fixed times for "As needed" — doses can be logged anytime.')

        st.divider()
        st.markdown("**Additional Info**")
        instructions = st.text_area("Special Instructions", height=70,
                                    placeholder="e.g. Take with food, avoid grapefruit")
        reminder_min = st.selectbox(
            "Remind me before each dose",
            options=REMINDER_WINDOWS,
            index=2,
            format_func=lambda m: f"{m} minutes before",
        )

        submitted = st.form_submit_button("💾 Add Medication", use_container_width=True)

    if submitted:
        errors = []
        if not name.strip():
            errors.append("Drug name is required.")
        if not dosage.strip():
            errors.append("Dosage is required.")
        if frequency != "As needed" and not scheduled_times:
            errors.append("Set at least one scheduled time.")

        if errors:
            for e in errors:
                st.error(e)
            return

        # Compute end date from duration
        duration_days = _DURATION_DAYS[duration]
        start_dt = datetime.combine(start_date, time.min)
        end_dt = (start_dt + timedelta(days=duration_days)) if duration_days else None

        med = db.add_medication(
            patient_id=patient_id,
            name=name.strip(),
            dosage=dosage.strip(),
            frequency=frequency,
            scheduled_times=scheduled_times,
            condition_tag=condition_tag,
            instructions=instructions.strip(),
            start_date=start_dt,
            end_date=end_dt,
        )

        # Auto-create reminders for today's scheduled times
        today = _utcnow().date()
        created_reminders = 0
        for t_str in scheduled_times:
            h, m_val = map(int, t_str.split(":"))
            scheduled_dt = datetime(today.year, today.month, today.day, h, m_val)
            remind_dt = scheduled_dt - timedelta(minutes=reminder_min)
            if remind_dt > _utcnow():
                db.create_reminder(
                    patient_id=patient_id,
                    medication_id=med.id,
                    reminder_time=remind_dt,
                    minutes_before=reminder_min,
                    message=(
                        f"⏰ Time to take your {med.name} ({med.dosage}) "
                        f"in {reminder_min} minutes. Stay on track!"
                    ),
                )
                created_reminders += 1

        end_label = end_dt.strftime("%b %d, %Y") if end_dt else "ongoing"
        st.success(
            f"✅ **{name}** ({dosage}) added — "
            f"{frequency}, {len(scheduled_times)} time(s)/day, "
            f"until {end_label}. "
            f"{created_reminders} reminder(s) scheduled for today."
        )
        st.rerun()


# ══════════════════════════════════════════════════════════════════════════════
# MEDICATION LIST  (with inline edit)
# ══════════════════════════════════════════════════════════════════════════════

def render_medication_list(patient_id: int) -> None:
    st.subheader("💊 Active Medications")
    meds = db.get_medications(patient_id)

    if not meds:
        st.info("No active medications. Add your first medication using the **Add Medication** tab.")
        return

    for med in meds:
        times = json.loads(med.scheduled_times or "[]")
        times_str = "  ·  ".join(times) if times else "As needed"
        start_str = med.start_date.strftime("%b %d, %Y") if med.start_date else "—"
        end_str = med.end_date.strftime("%b %d, %Y") if med.end_date else "Ongoing"

        with st.container(border=True):
            # ── Header row ────────────────────────────────────────────────────
            hcol1, hcol2, hcol3 = st.columns([5, 1, 1])
            with hcol1:
                st.markdown(f"### 💊 {med.name} &nbsp; `{med.dosage}`")
            with hcol2:
                edit_key = f"editing_{med.id}"
                label = "✏️ Edit" if not st.session_state.get(edit_key) else "✖ Cancel"
                if st.button(label, key=f"edit_btn_{med.id}", use_container_width=True):
                    st.session_state[edit_key] = not st.session_state.get(edit_key, False)
                    st.rerun()
            with hcol3:
                if st.button("🗑️ Del", key=f"del_{med.id}",
                             help="Deactivate", use_container_width=True):
                    db.deactivate_medication(med.id)
                    st.success(f"{med.name} deactivated.")
                    st.rerun()

            # ── Read-only view ─────────────────────────────────────────────────
            if not st.session_state.get(edit_key):
                col1, col2, col3 = st.columns(3)
                with col1:
                    st.markdown(f"**Frequency:** {med.frequency}")
                    st.markdown(f"**Times:** {times_str}")
                with col2:
                    st.markdown(f"**Duration:** {start_str} → {end_str}")
                    if med.condition_tag:
                        st.markdown(f"**Condition:** {med.condition_tag}")
                with col3:
                    if med.instructions:
                        st.markdown(f"**Instructions:** {med.instructions}")

                with st.expander("ℹ️ AI Drug Information"):
                    if st.button("Get AI Info", key=f"ai_{med.id}"):
                        from modules import ai_engine
                        with st.spinner("Loading drug information..."):
                            info = ai_engine.get_medication_info(
                                med.name, med.dosage,
                                med.condition_tag or "chronic condition",
                            )
                        st.session_state[f"med_info_{med.id}"] = info
                    if f"med_info_{med.id}" in st.session_state:
                        st.markdown(st.session_state[f"med_info_{med.id}"])

            # ── Inline edit form ───────────────────────────────────────────────
            else:
                _render_edit_form(med)


# ══════════════════════════════════════════════════════════════════════════════
# DAILY INTAKE LOGGING — per scheduled slot
# ══════════════════════════════════════════════════════════════════════════════


# ══════════════════════════════════════════════════════════════════════════════
# INLINE EDIT FORM
# ══════════════════════════════════════════════════════════════════════════════

def _render_edit_form(med) -> None:
    """Render an inline form to edit name, dosage, scheduled times, and more."""
    st.markdown("##### ✏️ Edit Medication")

    existing_times = json.loads(med.scheduled_times or "[]")

    with st.form(f"edit_form_{med.id}", clear_on_submit=False):
        col1, col2 = st.columns(2)
        with col1:
            new_name = st.text_input("Drug Name *", value=med.name)
            new_dosage = st.text_input("Dosage *", value=med.dosage)
            new_frequency = st.selectbox(
                "Frequency *",
                FREQUENCY_OPTIONS,
                index=FREQUENCY_OPTIONS.index(med.frequency)
                      if med.frequency in FREQUENCY_OPTIONS else 0,
            )
            new_condition = st.selectbox(
                "Related Condition",
                [""] + CHRONIC_CONDITIONS,
                index=([""] + CHRONIC_CONDITIONS).index(med.condition_tag)
                      if med.condition_tag in CHRONIC_CONDITIONS else 0,
            )
        with col2:
            new_instructions = st.text_area(
                "Special Instructions",
                value=med.instructions or "",
                height=90,
            )
            new_end_date = st.date_input(
                "End Date (optional)",
                value=med.end_date.date() if med.end_date else None,
            )

        st.markdown("**Scheduled Times** *(up to 4)*")
        # Pre-populate with existing saved times, or defaults for the frequency
        default_times = existing_times if existing_times else \
                        _FREQ_DEFAULT_TIMES.get(new_frequency, [])
        max_slots = min(max(len(default_times), 1), 4) \
                    if new_frequency != "As needed" else 0

        new_times: list[str] = []
        if max_slots > 0:
            tcols = st.columns(max_slots)
            for i in range(max_slots):
                with tcols[i]:
                    default_val = None
                    if i < len(default_times):
                        h, m = map(int, default_times[i].split(":"))
                        default_val = time(h, m)
                    t = st.time_input(
                        f"Time {i + 1}",
                        value=default_val,
                        key=f"edit_t_{med.id}_{i}",
                    )
                    if t is not None:
                        new_times.append(t.strftime("%H:%M"))
        else:
            st.info('No fixed times for "As needed".')

        save_col, _ = st.columns([1, 3])
        with save_col:
            saved = st.form_submit_button("💾 Save Changes", use_container_width=True)

    if saved:
        errors = []
        if not new_name.strip():
            errors.append("Drug name is required.")
        if not new_dosage.strip():
            errors.append("Dosage is required.")
        if new_frequency != "As needed" and not new_times:
            errors.append("Set at least one scheduled time.")
        if errors:
            for e in errors:
                st.error(e)
            return

        from datetime import time as dtime
        end_dt = datetime.combine(new_end_date, dtime.min) \
                 if new_end_date else None

        ok = db.update_medication(
            med_id=med.id,
            name=new_name.strip(),
            dosage=new_dosage.strip(),
            frequency=new_frequency,
            scheduled_times=new_times,
            condition_tag=new_condition,
            instructions=new_instructions.strip(),
            end_date=end_dt,
        )
        if ok:
            st.session_state[f"editing_{med.id}"] = False
            st.success(f"✅ **{new_name}** updated successfully.")
            st.rerun()
        else:
            st.error("Failed to save — medication not found.")



def render_log_intake(patient_id: int) -> None:
    st.subheader("📋 Log Today's Doses")

    meds = db.get_medications(patient_id)
    if not meds:
        st.info("No active medications. Add one first under **My Medications**.")
        return

    today = _utcnow().date()
    now = _utcnow()

    any_slots = False

    for med in meds:
        times = json.loads(med.scheduled_times or "[]")
        if not times:
            # "As needed" logging
            st.markdown(f"#### 💊 {med.name} — {med.dosage} *(as needed)*")
            with st.form(f"as_needed_{med.id}", clear_on_submit=True):
                col1, col2 = st.columns(2)
                with col1:
                    notes = st.text_input("Notes (optional)")
                    side_eff = st.text_input("Side effects (optional)")
                with col2:
                    log_time = st.time_input("Time taken", value=now.time())
                if st.form_submit_button("✅ Log As Taken", use_container_width=True):
                    taken_dt = datetime.combine(today, log_time)
                    db.log_medication(
                        patient_id=patient_id,
                        medication_id=med.id,
                        scheduled_time=taken_dt,
                        status="taken",
                        taken_time=taken_dt,
                        notes=notes,
                        side_effects=side_eff,
                    )
                    st.success(f"✅ {med.name} logged as taken.")
                    st.rerun()
            st.divider()
            any_slots = True
            continue

        st.markdown(f"#### 💊 {med.name} — {med.dosage}")
        st.caption(f"{med.frequency}  |  {med.condition_tag or 'General'}")

        for t_str in times:
            h, m_val = map(int, t_str.split(":"))
            scheduled_dt = datetime.combine(today, time(h, m_val))

            # Check if already logged
            existing = db.get_existing_log(patient_id, med.id, scheduled_dt)

            with st.container(border=True):
                lcol1, lcol2, lcol3, lcol4, lcol5 = st.columns([2, 2, 2, 2, 3])

                # Time label with overdue indicator
                is_past = scheduled_dt < now
                time_icon = "🕐" if not is_past else ("⚠️" if not existing else "")
                with lcol1:
                    st.markdown(f"**{time_icon} {t_str}**")
                    st.caption("overdue" if (is_past and not existing) else ("upcoming" if not is_past else ""))

                if existing:
                    status_icons = {"taken": "✅ Taken", "missed": "❌ Missed", "skipped": "⏭️ Skipped"}
                    status_label = status_icons.get(existing.status, existing.status)
                    with lcol2:
                        st.success(status_label) if existing.status == "taken" else \
                        st.error(status_label) if existing.status == "missed" else \
                        st.warning(status_label)
                    with lcol3:
                        st.caption(f"Logged at {existing.taken_time.strftime('%H:%M') if existing.taken_time else '—'}")
                    with lcol4:
                        if existing.side_effects:
                            st.caption(f"⚠️ {existing.side_effects}")
                    with lcol5:
                        # Allow updating the log
                        if st.button("↩️ Update", key=f"upd_{med.id}_{t_str}"):
                            st.session_state[f"show_update_{med.id}_{t_str}"] = True

                    if st.session_state.get(f"show_update_{med.id}_{t_str}"):
                        with st.form(f"update_{med.id}_{t_str}", clear_on_submit=True):
                            new_status = st.selectbox("New Status", ["taken", "missed", "skipped"])
                            new_notes = st.text_input("Notes")
                            new_se = st.text_input("Side effects")
                            if st.form_submit_button("Save Update"):
                                db.log_medication(
                                    patient_id=patient_id,
                                    medication_id=med.id,
                                    scheduled_time=scheduled_dt,
                                    status=new_status,
                                    notes=new_notes,
                                    side_effects=new_se,
                                )
                                st.session_state.pop(f"show_update_{med.id}_{t_str}", None)
                                st.rerun()
                else:
                    # Not yet logged — show action buttons
                    with lcol2:
                        if st.button("✅ Taken", key=f"taken_{med.id}_{t_str}", use_container_width=True):
                            db.log_medication(patient_id, med.id, scheduled_dt, "taken")
                            st.rerun()
                    with lcol3:
                        if st.button("❌ Missed", key=f"miss_{med.id}_{t_str}", use_container_width=True):
                            db.log_medication(patient_id, med.id, scheduled_dt, "missed")
                            st.rerun()
                    with lcol4:
                        if st.button("⏭️ Skip", key=f"skip_{med.id}_{t_str}", use_container_width=True):
                            db.log_medication(patient_id, med.id, scheduled_dt, "skipped")
                            st.rerun()
                    with lcol5:
                        # Quick note inline
                        if st.button("📝 Add Note", key=f"note_btn_{med.id}_{t_str}"):
                            st.session_state[f"show_note_{med.id}_{t_str}"] = True

                    if st.session_state.get(f"show_note_{med.id}_{t_str}"):
                        with st.form(f"note_form_{med.id}_{t_str}", clear_on_submit=True):
                            notes = st.text_input("Notes")
                            side_eff = st.text_input("Side effects")
                            status = st.selectbox("Status", ["taken", "missed", "skipped"])
                            if st.form_submit_button("Save"):
                                db.log_medication(patient_id, med.id, scheduled_dt, status,
                                                  notes=notes, side_effects=side_eff)
                                st.session_state.pop(f"show_note_{med.id}_{t_str}", None)
                                st.rerun()

            any_slots = True

        # Daily summary for this medication
        taken_today = sum(
            1 for t_str in times
            if (existing := db.get_existing_log(
                patient_id, med.id,
                datetime.combine(today, time(*map(int, t_str.split(":"))))
            )) and existing.status == "taken"
        )
        st.caption(f"Today: {taken_today}/{len(times)} doses taken")
        st.divider()

    if not any_slots:
        st.info("No medications with scheduled times to log today.")
