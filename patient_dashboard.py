"""
pages/patient_dashboard.py — Full patient-facing dashboard
Features: medication schedule, daily intake logging, reminders,
          adherence analytics, AI chat, alert threshold settings.
"""

from __future__ import annotations

import json
import hashlib
from datetime import datetime, timezone

import streamlit as st

from modules import auth, medication, reminders, analytics, ai_engine
from database import db_manager as db


def _utcnow() -> datetime:
    return datetime.now(timezone.utc).replace(tzinfo=None)


def render(user) -> None:
    # ── Reminder banner at very top (simulated push notification) ─────────────
    reminders.render_reminder_banner(user.id)

    with st.sidebar:
        st.markdown(f"### 👤 {user.full_name}")
        st.caption("Role: Patient")
        if user.conditions:
            st.caption(f"📋 {user.conditions}")
        st.divider()

        page = st.radio(
            "Navigation",
            options=[
                "🏠 Dashboard",
                "📋 Log Today's Doses",
                "💊 My Medications",
                "🔔 Reminders",
                "📊 Analytics",
                "🤖 AI Health Assistant",
                "⚙️ Settings",
            ],
            label_visibility="collapsed",
        )

        st.divider()
        if st.button("🚪 Logout", use_container_width=True):
            auth.logout()

    page_key = page.split(" ", 1)[1]

    if page_key == "Dashboard":
        _render_home(user)
    elif page_key == "Log Today's Doses":
        medication.render_log_intake(user.id)
    elif page_key == "My Medications":
        _render_medications_page(user)
    elif page_key == "Reminders":
        reminders.render_reminders_page(user.id)
    elif page_key == "Analytics":
        analytics.render_patient_analytics(user.id)
    elif page_key == "AI Health Assistant":
        _render_ai_chat(user)
    elif page_key == "Settings":
        _render_settings(user)


# ══════════════════════════════════════════════════════════════════════════════
# DASHBOARD HOME
# ══════════════════════════════════════════════════════════════════════════════

def _render_home(user) -> None:
    st.subheader(f"Welcome back, {user.full_name.split()[0]}! 👋")

    # KPI row
    stats7  = db.get_adherence_stats(user.id, days=7)
    stats30 = db.get_adherence_stats(user.id, days=30)
    threshold = float(getattr(user, "alert_threshold", 75) or 75)
    meds = db.get_medications(user.id)

    col1, col2, col3, col4 = st.columns(4)
    col1.metric("7-Day Adherence",  f"{stats7['rate']}%",
                "✅" if stats7["rate"] >= threshold else "⚠️ Below threshold",
                delta_color="normal" if stats7["rate"] >= threshold else "inverse")
    col2.metric("30-Day Adherence", f"{stats30['rate']}%")
    col3.metric("Active Medications", len(meds))
    col4.metric("Pending Reminders", len(db.get_all_reminders(user.id)))

    # Low-adherence patient alert
    if stats7["total"] > 0 and stats7["rate"] < threshold:
        st.warning(
            f"⚠️ Your 7-day adherence ({stats7['rate']}%) is below your alert "
            f"threshold ({threshold}%). Check your schedule!"
        )

    st.divider()

    # Today's schedule
    st.markdown("#### 📅 Today's Medication Schedule")
    today = _utcnow().date()

    if not meds:
        st.info("No active medications. Go to **My Medications** to add one.")
    else:
        for med in meds:
            times = json.loads(med.scheduled_times or "[]")
            if times:
                now = _utcnow()
                slots = []
                for t_str in times:
                    h, m = map(int, t_str.split(":"))
                    from datetime import time as dtime
                    sched_dt = datetime.combine(today, dtime(h, m))
                    existing = db.get_existing_log(user.id, med.id, sched_dt)
                    if existing:
                        icon = {"taken": "✅", "missed": "❌", "skipped": "⏭️"}.get(existing.status, "•")
                    elif sched_dt < now:
                        icon = "⚠️"   # overdue, not logged
                    else:
                        icon = "🕐"   # upcoming
                    slots.append(f"{icon} {t_str}")
                st.markdown(f"💊 **{med.name}** {med.dosage} — {' · '.join(slots)}")
            else:
                st.markdown(f"💊 **{med.name}** {med.dosage} — *(as needed)*")

    st.divider()

    # Today's progress bar
    today_logs = db.get_today_logs(user.id)
    if today_logs:
        taken = sum(1 for lg in today_logs if lg.status == "taken")
        total = len(today_logs)
        pct = taken / total
        st.markdown(f"#### Today's Progress: {taken}/{total} doses logged")
        st.progress(pct)
        if pct == 1.0:
            st.success("🎉 All doses logged for today — great job!")
        elif pct >= 0.75:
            st.info("👍 Good progress — keep it up!")
    else:
        st.markdown("#### Today's Progress")
        st.info("No doses logged yet today. Go to **Log Today's Doses** to start.")

    st.divider()

    # Daily tip
    st.markdown("#### 💡 Tip of the Day")
    tips = [
        "Taking medications at the same time each day builds a consistent habit.",
        "Use a pill organiser to easily track whether you've taken your dose.",
        "Setting phone alarms is a simple and effective reminder strategy.",
        "If you miss a dose, take it as soon as you remember — unless it's close to your next dose time.",
        "Keep a medication diary to track side effects and share with your doctor.",
        "Pairing medication with a daily routine (like breakfast) improves consistency.",
        "Never stop a medication without consulting your doctor, even if you feel better.",
    ]
    tip_idx = int(hashlib.md5(str(today).encode()).hexdigest(), 16) % len(tips)
    st.info(tips[tip_idx])


# ══════════════════════════════════════════════════════════════════════════════
# MEDICATIONS PAGE
# ══════════════════════════════════════════════════════════════════════════════

def _render_medications_page(user) -> None:
    tab1, tab2 = st.tabs(["My Medications", "Add Medication"])
    with tab1:
        medication.render_medication_list(user.id)
    with tab2:
        medication.render_add_medication(user.id)


# ══════════════════════════════════════════════════════════════════════════════
# AI CHAT
# ══════════════════════════════════════════════════════════════════════════════

def _render_ai_chat(user) -> None:
    st.subheader("🤖 AI Health Assistant")
    st.caption("Powered by Gemini 2.5 Flash — Your personal medication adherence companion")

    if "chat_history_display" not in st.session_state:
        st.session_state["chat_history_display"] = []
        history = db.get_ai_history(user.id, limit=30)
        for h in history:
            st.session_state["chat_history_display"].append(
                {"role": "user" if h.role == "user" else "assistant",
                 "content": h.content}
            )

    for msg in st.session_state["chat_history_display"]:
        with st.chat_message(msg["role"]):
            st.markdown(msg["content"])

    meds = db.get_medications(user.id)
    patient_ctx = {
        "name": user.full_name,
        "conditions": user.conditions,
        "medications": [{"name": m.name, "dosage": m.dosage, "frequency": m.frequency}
                        for m in meds],
    }

    if prompt := st.chat_input("Ask about your medications, adherence tips, side effects..."):
        st.session_state["chat_history_display"].append({"role": "user", "content": prompt})
        with st.chat_message("user"):
            st.markdown(prompt)

        with st.chat_message("assistant"):
            with st.spinner("Thinking..."):
                reply = ai_engine.chat_with_ai(
                    user_id=user.id,
                    user_message=prompt,
                    patient_context=patient_ctx if not db.get_ai_history(user.id, limit=1) else None,
                )
            st.markdown(reply)

        st.session_state["chat_history_display"].append({"role": "assistant", "content": reply})

    col1, col2 = st.columns([4, 1])
    with col2:
        if st.button("Clear Chat", use_container_width=True):
            db.clear_ai_history(user.id)
            st.session_state.pop("chat_history_display", None)
            st.rerun()

    st.divider()
    st.markdown("#### ⚡ Quick Actions")
    qcol1, qcol2 = st.columns(2)
    with qcol1:
        if st.button("📊 Analyse My Adherence", use_container_width=True):
            stats = db.get_adherence_stats(user.id, days=30)
            stats["days"] = 30
            with st.spinner("Analysing..."):
                result = ai_engine.analyse_adherence(
                    patient_name=user.full_name, stats=stats,
                    conditions=user.conditions or "Not specified",
                )
            st.markdown(result)
    with qcol2:
        if st.button("💡 Get Adherence Tips", use_container_width=True):
            meds_list = [{"name": m.name} for m in meds]
            with st.spinner("Generating tips..."):
                result = ai_engine.suggest_adherence_improvements(
                    conditions=user.conditions or "chronic condition",
                    medications=meds_list, barriers="",
                )
            st.markdown(result)


# ══════════════════════════════════════════════════════════════════════════════
# SETTINGS PAGE — alert threshold + profile
# ══════════════════════════════════════════════════════════════════════════════

def _render_settings(user) -> None:
    st.subheader("⚙️ Settings")

    tab1, tab2 = st.tabs(["Alert Threshold", "My Profile"])

    with tab1:
        st.markdown("#### 🚨 Alert Threshold")
        st.caption(
            "When your adherence drops below this percentage, you will see a warning "
            "on your dashboard and your caregiver/doctor will be notified."
        )
        current = float(getattr(user, "alert_threshold", 75) or 75)
        st.metric("Current Threshold", f"{current}%")

        new_threshold = st.slider(
            "Set new alert threshold",
            min_value=10, max_value=100,
            value=int(current), step=5,
            format="%d%%",
        )
        if st.button("💾 Save Alert Threshold", use_container_width=True):
            db.update_alert_threshold(user.id, float(new_threshold))
            # Refresh user object in session
            updated = db.get_user_by_id(user.id)
            if updated:
                st.session_state["user"] = updated
            st.success(f"✅ Alert threshold updated to **{new_threshold}%**")
            st.rerun()

        st.divider()
        st.markdown("**Threshold Guide:**")
        st.markdown("- 🟢 **≥ 90%** — Excellent adherence")
        st.markdown("- 🟡 **75–89%** — Good adherence (recommended minimum)")
        st.markdown("- 🟠 **50–74%** — Fair adherence")
        st.markdown("- 🔴 **< 50%** — Poor adherence — urgent attention needed")

    with tab2:
        st.markdown("#### 👤 My Profile")
        st.markdown(f"**Name:** {user.full_name}")
        st.markdown(f"**Username:** @{user.username}")
        st.markdown(f"**Email:** {user.email}")
        st.markdown(f"**Role:** {user.role.value.capitalize()}")
        st.markdown(f"**Conditions:** {user.conditions or 'None listed'}")
        st.markdown(f"**Member since:** {user.created_at.strftime('%B %d, %Y')}")
