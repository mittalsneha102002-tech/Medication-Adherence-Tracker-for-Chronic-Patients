"""
modules/analytics.py — Adherence analytics, trend charts, and alerts
Features: adherence % dashboard, daily/weekly/monthly trend charts,
          per-medication breakdown, configurable alert thresholds.
"""

from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from collections import defaultdict

import pandas as pd
import plotly.graph_objects as go
import plotly.express as px
import streamlit as st

from config import ADHERENCE_EXCELLENT, ADHERENCE_GOOD, ADHERENCE_FAIR
from database import db_manager as db
from modules import ai_engine


def _utcnow() -> datetime:
    return datetime.now(timezone.utc).replace(tzinfo=None)


# ── Colour palette ─────────────────────────────────────────────────────────────
COLOR_TAKEN   = "#22c55e"
COLOR_MISSED  = "#ef4444"
COLOR_SKIPPED = "#f59e0b"
COLOR_LINE    = "#3b82f6"
COLOR_THRESH  = "#f43f5e"


# ══════════════════════════════════════════════════════════════════════════════
# PATIENT ANALYTICS PAGE
# ══════════════════════════════════════════════════════════════════════════════

def render_patient_analytics(patient_id: int) -> None:
    st.subheader("📊 Adherence Analytics")

    user = st.session_state.get("user")
    threshold = float(getattr(user, "alert_threshold", 75) or 75)

    tab_dash, tab_week, tab_month, tab_meds, tab_ai = st.tabs([
        "Dashboard", "Weekly Trend", "Monthly Trend",
        "Per Medication", "AI Analysis"
    ])

    with tab_dash:
        period = st.selectbox("Period", [7, 14, 30, 60, 90], index=2,
                              format_func=lambda d: f"Last {d} days",
                              key="dash_period")
        stats = db.get_adherence_stats(patient_id, days=period)
        stats["days"] = period
        logs = db.get_logs_for_patient(patient_id, days=period)
        _render_kpi_metrics(stats, threshold)
        st.divider()
        col1, col2 = st.columns(2)
        with col1:
            _render_donut_chart(stats)
        with col2:
            _render_daily_bar(logs, period, threshold)

    with tab_week:
        weeks = st.slider("Number of weeks", 4, 24, 12, key="week_slider")
        _render_weekly_trend(patient_id, weeks, threshold)

    with tab_month:
        months = st.slider("Number of months", 3, 12, 6, key="month_slider")
        _render_monthly_trend(patient_id, months, threshold)

    with tab_meds:
        period2 = st.selectbox("Period", [7, 14, 30, 60, 90], index=2,
                               format_func=lambda d: f"Last {d} days",
                               key="meds_period")
        logs2 = db.get_logs_for_patient(patient_id, days=period2)
        _render_medication_breakdown(patient_id, logs2)

    with tab_ai:
        period3 = st.selectbox("Period", [7, 14, 30, 60, 90], index=2,
                               format_func=lambda d: f"Last {d} days",
                               key="ai_period_pat")
        stats3 = db.get_adherence_stats(patient_id, days=period3)
        stats3["days"] = period3
        _render_ai_analysis(patient_id, stats3)


# ══════════════════════════════════════════════════════════════════════════════
# KPI METRICS
# ══════════════════════════════════════════════════════════════════════════════

def _render_kpi_metrics(stats: dict, threshold: float = 75.0) -> None:
    rate = stats["rate"]
    if rate >= ADHERENCE_EXCELLENT:
        badge = "🟢 Excellent"
    elif rate >= ADHERENCE_GOOD:
        badge = "🟡 Good"
    elif rate >= ADHERENCE_FAIR:
        badge = "🟠 Fair"
    else:
        badge = "🔴 Needs Attention"

    col1, col2, col3, col4, col5 = st.columns(5)
    col1.metric("Adherence Rate", f"{rate}%", badge)
    col2.metric("Doses Taken", stats["taken"], f"of {stats['total']}")
    col3.metric("Doses Missed", stats["missed"])
    col4.metric("Doses Skipped", stats["skipped"])
    col5.metric("Alert Threshold", f"{threshold}%",
                "✅ Above" if rate >= threshold else "⚠️ Below",
                delta_color="normal" if rate >= threshold else "inverse")

    if stats["total"] > 0 and rate < threshold:
        st.warning(
            f"⚠️ Your adherence ({rate}%) has dropped below your alert threshold ({threshold}%). "
            "Please review your medication schedule."
        )


# ══════════════════════════════════════════════════════════════════════════════
# DAILY BAR CHART
# ══════════════════════════════════════════════════════════════════════════════

def _render_daily_bar(logs, period: int, threshold: float = 75.0) -> None:
    if not logs:
        st.info("No trend data available.")
        return

    daily: dict[str, dict] = defaultdict(lambda: {"taken": 0, "missed": 0, "skipped": 0})
    for log in logs:
        date_key = log.scheduled_time.date().isoformat()
        if log.status in daily[date_key]:
            daily[date_key][log.status] += 1

    end_date = _utcnow().date()
    start_date = end_date - timedelta(days=period - 1)
    all_dates = [(start_date + timedelta(days=i)).isoformat() for i in range(period)]
    rows = [{"date": d, **daily.get(d, {"taken": 0, "missed": 0, "skipped": 0})}
            for d in all_dates]
    df = pd.DataFrame(rows)

    fig = go.Figure()
    fig.add_trace(go.Bar(name="Taken",   x=df["date"], y=df["taken"],   marker_color=COLOR_TAKEN))
    fig.add_trace(go.Bar(name="Missed",  x=df["date"], y=df["missed"],  marker_color=COLOR_MISSED))
    fig.add_trace(go.Bar(name="Skipped", x=df["date"], y=df["skipped"], marker_color=COLOR_SKIPPED))
    fig.update_layout(
        barmode="stack", title="Daily Dose Log",
        xaxis_title="Date", yaxis_title="Doses",
        height=320, margin=dict(t=40, b=10, l=10, r=10),
    )
    st.plotly_chart(fig, use_container_width=True)


# ══════════════════════════════════════════════════════════════════════════════
# WEEKLY TREND CHART
# ══════════════════════════════════════════════════════════════════════════════

def _render_weekly_trend(patient_id: int, weeks: int, threshold: float) -> None:
    data = db.get_weekly_adherence(patient_id, weeks=weeks)
    df = pd.DataFrame(data)

    if df.empty or df["rate"].isna().all():
        st.info("Not enough data for a weekly trend chart. Log some doses first.")
        return

    fig = go.Figure()
    fig.add_trace(go.Scatter(
        x=df["week"], y=df["rate"],
        mode="lines+markers",
        name="Adherence %",
        line=dict(color=COLOR_LINE, width=3),
        marker=dict(size=8),
        connectgaps=False,
    ))
    # Threshold line
    fig.add_hline(
        y=threshold,
        line_dash="dash",
        line_color=COLOR_THRESH,
        annotation_text=f"Alert threshold ({threshold}%)",
        annotation_position="top right",
    )
    # Colour bands
    fig.add_hrect(y0=ADHERENCE_EXCELLENT, y1=100,   fillcolor="#22c55e", opacity=0.05, line_width=0)
    fig.add_hrect(y0=ADHERENCE_GOOD,      y1=ADHERENCE_EXCELLENT, fillcolor="#f59e0b", opacity=0.05, line_width=0)
    fig.add_hrect(y0=0,                   y1=ADHERENCE_GOOD,      fillcolor="#ef4444", opacity=0.05, line_width=0)

    fig.update_layout(
        title=f"Weekly Adherence Trend (last {weeks} weeks)",
        xaxis_title="Week",
        yaxis_title="Adherence %",
        yaxis=dict(range=[0, 105]),
        height=380,
        margin=dict(t=50, b=40, l=10, r=10),
    )
    st.plotly_chart(fig, use_container_width=True)

    # Summary table
    df_display = df.copy()
    df_display["rate"] = df_display["rate"].apply(
        lambda r: f"{r}%" if r is not None else "No data"
    )
    df_display.columns = ["Week", "Total Doses", "Taken", "Adherence %"]
    st.dataframe(df_display, use_container_width=True, hide_index=True)


# ══════════════════════════════════════════════════════════════════════════════
# MONTHLY TREND CHART
# ══════════════════════════════════════════════════════════════════════════════

def _render_monthly_trend(patient_id: int, months: int, threshold: float) -> None:
    data = db.get_monthly_adherence(patient_id, months=months)
    df = pd.DataFrame(data)

    if df.empty or df["rate"].isna().all():
        st.info("Not enough data for a monthly trend chart. Log some doses first.")
        return

    # Bar chart for monthly view
    fig = go.Figure()
    colors = [
        COLOR_TAKEN if (r is not None and r >= threshold) else COLOR_MISSED
        for r in df["rate"]
    ]
    fig.add_trace(go.Bar(
        x=df["month"],
        y=df["rate"].fillna(0),
        marker_color=colors,
        text=[f"{r}%" if r is not None else "—" for r in df["rate"]],
        textposition="outside",
        name="Adherence %",
    ))
    fig.add_hline(
        y=threshold,
        line_dash="dash",
        line_color=COLOR_THRESH,
        annotation_text=f"Threshold ({threshold}%)",
        annotation_position="top right",
    )
    fig.update_layout(
        title=f"Monthly Adherence (last {months} months)",
        xaxis_title="Month",
        yaxis_title="Adherence %",
        yaxis=dict(range=[0, 115]),
        height=360,
        margin=dict(t=50, b=40, l=10, r=10),
    )
    st.plotly_chart(fig, use_container_width=True)

    # Summary table
    df_display = df.copy()
    df_display["rate"] = df_display["rate"].apply(
        lambda r: f"{r}%" if r is not None else "No data"
    )
    df_display.columns = ["Month", "Total Doses", "Taken", "Adherence %"]
    st.dataframe(df_display, use_container_width=True, hide_index=True)


# ══════════════════════════════════════════════════════════════════════════════
# DONUT CHART
# ══════════════════════════════════════════════════════════════════════════════

def _render_donut_chart(stats: dict) -> None:
    if stats["total"] == 0:
        st.info("No log data available for this period.")
        return

    fig = go.Figure(go.Pie(
        labels=["Taken", "Missed", "Skipped"],
        values=[stats["taken"], stats["missed"], stats["skipped"]],
        hole=0.55,
        marker=dict(colors=[COLOR_TAKEN, COLOR_MISSED, COLOR_SKIPPED]),
        textinfo="label+percent",
    ))
    fig.update_layout(
        title="Dose Status Breakdown",
        showlegend=True,
        height=320,
        margin=dict(t=40, b=10, l=10, r=10),
    )
    st.plotly_chart(fig, use_container_width=True)


# ══════════════════════════════════════════════════════════════════════════════
# PER-MEDICATION BREAKDOWN
# ══════════════════════════════════════════════════════════════════════════════

def _render_medication_breakdown(patient_id: int, logs) -> None:
    st.markdown("#### Per-Medication Breakdown")
    if not logs:
        st.info("No data available.")
        return

    med_stats: dict[int, dict] = defaultdict(
        lambda: {"taken": 0, "missed": 0, "skipped": 0, "total": 0}
    )
    med_names: dict[int, str] = {}

    for log in logs:
        med_stats[log.medication_id]["total"] += 1
        if log.status in med_stats[log.medication_id]:
            med_stats[log.medication_id][log.status] += 1
        if log.medication_id not in med_names:
            med = db.get_medication_by_id(log.medication_id)
            med_names[log.medication_id] = med.name if med else f"Med #{log.medication_id}"

    rows = []
    for mid, s in med_stats.items():
        rate = round((s["taken"] / s["total"]) * 100, 1) if s["total"] > 0 else 0.0
        rows.append({
            "Medication": med_names.get(mid, f"#{mid}"),
            "Total": s["total"],
            "Taken": s["taken"],
            "Missed": s["missed"],
            "Skipped": s["skipped"],
            "Adherence %": rate,
        })

    if not rows:
        return

    df = pd.DataFrame(rows).sort_values("Adherence %", ascending=True)
    fig = px.bar(
        df, x="Adherence %", y="Medication", orientation="h",
        color="Adherence %",
        color_continuous_scale=["#ef4444", "#f59e0b", "#22c55e"],
        range_color=[0, 100],
        title="Adherence Rate by Medication",
        text="Adherence %",
    )
    fig.update_traces(texttemplate="%{text}%", textposition="outside")
    fig.update_layout(height=max(250, 65 * len(rows)),
                      margin=dict(t=40, b=10, l=10, r=10))
    st.plotly_chart(fig, use_container_width=True)
    st.dataframe(df, use_container_width=True, hide_index=True)


# ══════════════════════════════════════════════════════════════════════════════
# AI ANALYSIS
# ══════════════════════════════════════════════════════════════════════════════

def _render_ai_analysis(patient_id: int, stats: dict) -> None:
    st.markdown("#### 🤖 AI Adherence Analysis")
    user = st.session_state.get("user")
    conditions = user.conditions if user else ""

    if st.button("Generate AI Analysis", use_container_width=True):
        with st.spinner("Analysing your adherence with AI..."):
            analysis = ai_engine.analyse_adherence(
                patient_name=user.full_name if user else "Patient",
                stats=stats,
                conditions=conditions or "Not specified",
            )
        st.markdown(analysis)


# ══════════════════════════════════════════════════════════════════════════════
# CAREGIVER / DOCTOR VIEWS
# ══════════════════════════════════════════════════════════════════════════════

def render_caregiver_analytics(patient, days: int = 30) -> None:
    threshold = float(getattr(patient, "alert_threshold", 75) or 75)
    stats = db.get_adherence_stats(patient.id, days=days)
    stats["days"] = days
    logs = db.get_logs_for_patient(patient.id, days=days)

    st.markdown(f"#### Adherence Overview — {patient.full_name}")
    _render_kpi_metrics(stats, threshold)

    col1, col2 = st.columns(2)
    with col1:
        _render_donut_chart(stats)
    with col2:
        _render_daily_bar(logs, days, threshold)

    tab_w, tab_m = st.tabs(["Weekly Trend", "Monthly Trend"])
    with tab_w:
        _render_weekly_trend(patient.id, 8, threshold)
    with tab_m:
        _render_monthly_trend(patient.id, 6, threshold)

    _render_medication_breakdown(patient.id, logs)


def render_doctor_summary(patient, days: int = 30) -> None:
    threshold = float(getattr(patient, "alert_threshold", 75) or 75)
    stats = db.get_adherence_stats(patient.id, days=days)
    stats["days"] = days
    logs = db.get_logs_for_patient(patient.id, days=days)
    meds = db.get_medications(patient.id)

    med_dicts = [{"name": m.name, "dosage": m.dosage, "frequency": m.frequency} for m in meds]
    side_effects = list({
        lg.side_effects for lg in logs if lg.side_effects and lg.side_effects.strip()
    })

    st.markdown(f"### Clinical Summary — {patient.full_name}")
    st.caption(f"Conditions: {patient.conditions or 'Not specified'}")

    _render_kpi_metrics(stats, threshold)

    col1, col2 = st.columns(2)
    with col1:
        _render_donut_chart(stats)
    with col2:
        _render_daily_bar(logs, days, threshold)

    tab_w, tab_m = st.tabs(["Weekly Trend", "Monthly Trend"])
    with tab_w:
        _render_weekly_trend(patient.id, 8, threshold)
    with tab_m:
        _render_monthly_trend(patient.id, 6, threshold)

    _render_medication_breakdown(patient.id, logs)

    st.divider()
    st.markdown("#### 🤖 AI Clinical Summary")
    if st.button(f"Generate AI Clinical Summary", use_container_width=True, key=f"ai_clin_{patient.id}"):
        with st.spinner("Generating clinical summary..."):
            summary = ai_engine.summarise_patient_for_doctor(
                patient_name=patient.full_name,
                conditions=patient.conditions or "Not specified",
                medications=med_dicts,
                stats=stats,
                recent_side_effects=side_effects,
            )
        st.markdown(summary)
