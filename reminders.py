"""
modules/reminders.py — Reminder display and management
Features: simulated push-notification banners (auto-checked on every page load),
          overdue alerts, schedule/dismiss reminders.
"""

from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone, time as dtime

import streamlit as st

from database import db_manager as db


def _utcnow() -> datetime:
    return datetime.now(timezone.utc).replace(tzinfo=None)


# ══════════════════════════════════════════════════════════════════════════════
# SIMULATED PUSH NOTIFICATION BANNER (auto-runs on every page load)
# ══════════════════════════════════════════════════════════════════════════════

def render_reminder_banner(patient_id: int) -> None:
    """
    Show due/overdue reminders as dismissable notification banners.
    Also auto-generates upcoming reminders from today's medication schedule
    if none exist yet for the current day.
    """
    _ensure_todays_reminders(patient_id)

    now = _utcnow()
    reminders = db.get_pending_reminders(patient_id)

    if not reminders:
        return

    overdue = [r for r in reminders if r.reminder_time <= now]
    upcoming = [r for r in reminders if r.reminder_time > now]

    # ── Overdue: show red notification banner ────────────────────────────────
    for r in overdue:
        med = db.get_medication_by_id(r.medication_id)
        med_label = f"**{med.name} {med.dosage}**" if med else "your medication"
        mins_late = int((now - r.reminder_time).total_seconds() / 60)
        late_label = f"{mins_late} min ago" if mins_late < 60 else f"{mins_late // 60}h {mins_late % 60}m ago"

        with st.container():
            cols = st.columns([9, 1])
            with cols[0]:
                st.error(
                    f"🔔 **Overdue Reminder** — Time to take {med_label}! "
                    f"*(was due {late_label})*\n\n"
                    f"{r.message}"
                )
            with cols[1]:
                if st.button("✓", key=f"dismiss_banner_{r.id}", help="Dismiss"):
                    db.dismiss_reminder(r.id)
                    st.rerun()

    # ── Upcoming: show a softer info banner ──────────────────────────────────
    if upcoming:
        next_r = upcoming[0]
        med = db.get_medication_by_id(next_r.medication_id)
        med_label = f"{med.name} {med.dosage}" if med else "your medication"
        mins_away = int((next_r.reminder_time - now).total_seconds() / 60)
        if mins_away <= 30:
            st.info(
                f"⏰ **Upcoming:** {med_label} in {mins_away} minute(s)  "
                f"—  {next_r.reminder_time.strftime('%H:%M')}"
            )


def _ensure_todays_reminders(patient_id: int) -> None:
    """
    Auto-create reminders for today's scheduled doses if they don't exist yet.
    This simulates what a background push-notification service would do.
    """
    today = _utcnow().date()
    session_key = f"reminders_seeded_{patient_id}_{today.isoformat()}"
    if st.session_state.get(session_key):
        return  # already done this session

    meds = db.get_medications(patient_id)
    for med in meds:
        times = json.loads(med.scheduled_times or "[]")
        for t_str in times:
            h, m = map(int, t_str.split(":"))
            scheduled_dt = datetime.combine(today, dtime(h, m))
            remind_dt = scheduled_dt - timedelta(minutes=15)  # default 15 min before

            if remind_dt < _utcnow() - timedelta(hours=1):
                continue  # too far in the past, skip

            # Only create if none already exists for this med+time today
            existing = db.get_existing_log(patient_id, med.id, scheduled_dt)
            already_reminded = any(
                abs((r.reminder_time - remind_dt).total_seconds()) < 300
                for r in db.get_all_reminders(patient_id)
            )
            if not already_reminded and not existing:
                db.create_reminder(
                    patient_id=patient_id,
                    medication_id=med.id,
                    reminder_time=remind_dt,
                    minutes_before=15,
                    message=(
                        f"⏰ Don't forget: {med.name} ({med.dosage}) "
                        f"at {t_str}. Staying consistent helps your health!"
                    ),
                )

    st.session_state[session_key] = True


# ══════════════════════════════════════════════════════════════════════════════
# REMINDERS MANAGEMENT PAGE
# ══════════════════════════════════════════════════════════════════════════════

def render_reminders_page(patient_id: int) -> None:
    st.subheader("🔔 Medication Reminders")
    st.caption("Reminders are auto-generated 15 min before each scheduled dose every day.")

    tab1, tab2 = st.tabs(["Active Reminders", "Schedule Custom Reminder"])

    with tab1:
        _render_active_reminders(patient_id)

    with tab2:
        _render_schedule_reminder(patient_id)


def _render_active_reminders(patient_id: int) -> None:
    reminders = db.get_all_reminders(patient_id)

    if not reminders:
        st.info("No active reminders. They will appear automatically before each scheduled dose.")
        return

    now = _utcnow()

    # Group by status
    overdue = [r for r in reminders if r.reminder_time <= now]
    upcoming_today = [
        r for r in reminders
        if r.reminder_time > now and r.reminder_time.date() == now.date()
    ]
    future = [
        r for r in reminders
        if r.reminder_time > now and r.reminder_time.date() > now.date()
    ]

    def _reminder_card(r, status_label: str, color_fn):
        med = db.get_medication_by_id(r.medication_id)
        med_name = f"{med.name} {med.dosage}" if med else "Unknown"
        with st.container(border=True):
            cols = st.columns([4, 3, 2])
            with cols[0]:
                st.markdown(f"**{med_name}**")
                st.caption(r.message[:100] + ("…" if len(r.message) > 100 else ""))
            with cols[1]:
                color_fn(f"{status_label}  |  {r.reminder_time.strftime('%b %d · %H:%M')}")
            with cols[2]:
                if st.button("✓ Dismiss", key=f"rem_dismiss_{r.id}", use_container_width=True):
                    db.dismiss_reminder(r.id)
                    st.rerun()

    if overdue:
        st.markdown("##### 🔴 Overdue")
        for r in overdue:
            mins_late = int((now - r.reminder_time).total_seconds() / 60)
            _reminder_card(r, f"⚠️ {mins_late}m overdue", st.error)

    if upcoming_today:
        st.markdown("##### 🟡 Due Today")
        for r in upcoming_today:
            mins_away = int((r.reminder_time - now).total_seconds() / 60)
            _reminder_card(r, f"⏰ In {mins_away} min", st.warning)

    if future:
        st.markdown("##### 🟢 Upcoming")
        for r in future:
            _reminder_card(r, f"🕐 {r.reminder_time.strftime('%b %d · %H:%M')}", st.info)


def _render_schedule_reminder(patient_id: int) -> None:
    meds = db.get_medications(patient_id)
    if not meds:
        st.warning("Add medications first before scheduling reminders.")
        return

    med_options = {m.id: f"{m.name} — {m.dosage}" for m in meds}

    with st.form("schedule_reminder_form", clear_on_submit=True):
        med_id = st.selectbox(
            "Select Medication",
            options=list(med_options.keys()),
            format_func=lambda k: med_options[k],
        )
        col1, col2 = st.columns(2)
        with col1:
            reminder_date = st.date_input("Reminder Date", value=_utcnow().date())
            reminder_time_val = st.time_input("Reminder Time", value=dtime(8, 0))
        with col2:
            minutes_before = st.selectbox(
                "Minutes before dose", [5, 10, 15, 30, 60], index=2
            )
            custom_message = st.text_area("Custom message (optional)", height=70,
                                          placeholder="Leave blank for auto-generated message")

        submitted = st.form_submit_button("📅 Schedule Reminder", use_container_width=True)

    if submitted:
        reminder_dt = datetime.combine(reminder_date, reminder_time_val)
        selected_med = next((m for m in meds if m.id == med_id), None)

        msg = custom_message.strip() if custom_message.strip() else (
            f"⏰ Time to take {selected_med.name} ({selected_med.dosage}) "
            f"in {minutes_before} minutes. Keep it up!" if selected_med else "Time for your medication!"
        )

        db.create_reminder(
            patient_id=patient_id,
            medication_id=med_id,
            reminder_time=reminder_dt,
            minutes_before=minutes_before,
            message=msg,
        )
        st.success(f"✅ Reminder scheduled for **{reminder_dt.strftime('%b %d, %Y at %H:%M')}**")
        st.rerun()
