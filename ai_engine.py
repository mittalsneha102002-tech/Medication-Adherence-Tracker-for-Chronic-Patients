"""
modules/ai_engine.py — Gemini 2.5 Flash AI integration (google-genai SDK v2)
Provides: medication advice, adherence analysis, side-effect guidance,
          personalised reminders, and a general health chat assistant.
"""

from __future__ import annotations

from typing import Optional

import streamlit as st
from google import genai
from google.genai import types as genai_types

from config import GEMINI_API_KEY, GEMINI_MODEL
from database import db_manager as db


# ── Initialise Gemini client ──────────────────────────────────────────────────

def _get_client() -> Optional[genai.Client]:
    """Return a cached Gemini client stored in st.session_state."""
    if "gemini_client" not in st.session_state:
        if not GEMINI_API_KEY:
            return None
        st.session_state["gemini_client"] = genai.Client(api_key=GEMINI_API_KEY)
    return st.session_state["gemini_client"]


def _system_prompt() -> str:
    return (
        "You are MedAdhere AI, a compassionate and knowledgeable medical adherence assistant "
        "specialised in helping chronic-disease patients, their caregivers, and doctors.\n\n"
        "Your responsibilities:\n"
        "1. Help patients understand their medications and why adherence matters.\n"
        "2. Provide practical tips to improve medication adherence.\n"
        "3. Explain common side effects and when to seek emergency care.\n"
        "4. Analyse adherence trends and flag concerning patterns.\n"
        "5. Support caregivers with monitoring strategies.\n"
        "6. Assist doctors with adherence reports and patient summaries.\n\n"
        "Guidelines:\n"
        "- Always encourage patients to consult their doctor for medical decisions.\n"
        "- Be empathetic, clear, and concise.\n"
        "- Use plain language; avoid jargon unless asked.\n"
        "- Never prescribe medications or change dosages.\n"
        "- Respond in English by default."
    )


# ── Core generation helper ────────────────────────────────────────────────────

def _generate(prompt: str, history: list[dict] | None = None) -> str:
    """Send a prompt (with optional chat history) to Gemini and return text."""
    client = _get_client()
    if client is None:
        return (
            "⚠️ Gemini API key not configured. "
            "Please add GEMINI_API_KEY to .streamlit/secrets.toml and restart the app."
        )
    try:
        # Build contents list
        contents: list = []

        if history:
            for turn in history:
                role = turn["role"]   # "user" or "model"
                text = turn["parts"][0] if isinstance(turn["parts"], list) else turn["parts"]
                contents.append(
                    genai_types.Content(
                        role=role,
                        parts=[genai_types.Part(text=text)],
                    )
                )

        # Append the current user message
        contents.append(
            genai_types.Content(
                role="user",
                parts=[genai_types.Part(text=prompt)],
            )
        )

        config = genai_types.GenerateContentConfig(
            system_instruction=_system_prompt(),
            temperature=0.7,
            max_output_tokens=1024,
        )

        response = client.models.generate_content(
            model=GEMINI_MODEL,
            contents=contents,
            config=config,
        )
        return response.text or "⚠️ Empty response from AI."

    except Exception as exc:
        return f"⚠️ AI error: {exc}"


# ══════════════════════════════════════════════════════════════════════════════
# PUBLIC API
# ══════════════════════════════════════════════════════════════════════════════

def chat_with_ai(
    user_id: int,
    user_message: str,
    patient_context: dict | None = None,
) -> str:
    """
    Multi-turn chat. History is loaded from DB and appended after each turn.
    patient_context: optional dict with name, conditions, medications list.
    """
    history_rows = db.get_ai_history(user_id, limit=20)
    gemini_history = [
        {"role": row.role, "parts": [row.content]}
        for row in history_rows
    ]

    # Prepend patient context into the first user message if no history yet
    context_prefix = ""
    if patient_context and not gemini_history:
        context_prefix = _build_context_prefix(patient_context)

    full_message = f"{context_prefix}{user_message}" if context_prefix else user_message

    reply = _generate(full_message, gemini_history)

    # Persist both turns
    db.save_ai_message(user_id, "user", user_message)
    db.save_ai_message(user_id, "model", reply)

    return reply


def _build_context_prefix(ctx: dict) -> str:
    lines = [
        f"Patient name: {ctx.get('name', 'Unknown')}",
        f"Chronic conditions: {ctx.get('conditions', 'None listed')}",
    ]
    meds = ctx.get("medications", [])
    if meds:
        med_list = "; ".join(
            f"{m['name']} {m['dosage']} ({m['frequency']})" for m in meds
        )
        lines.append(f"Current medications: {med_list}")
    lines.append("\nWith this context in mind, please answer the following:\n")
    return "\n".join(lines)


def analyse_adherence(patient_name: str, stats: dict, conditions: str) -> str:
    """Return AI analysis of a patient's adherence statistics."""
    prompt = (
        f"Analyse the following medication adherence data for {patient_name}:\n\n"
        f"Chronic conditions: {conditions}\n"
        f"Period: last {stats.get('days', 30)} days\n"
        f"Total scheduled doses: {stats['total']}\n"
        f"Doses taken: {stats['taken']}\n"
        f"Doses missed: {stats['missed']}\n"
        f"Doses skipped: {stats['skipped']}\n"
        f"Adherence rate: {stats['rate']}%\n\n"
        "Please provide:\n"
        "1. A brief interpretation of the adherence rate.\n"
        "2. Potential health risks if this pattern continues.\n"
        "3. Three actionable, personalised tips to improve adherence.\n"
        "4. Any red flags that the doctor should be aware of.\n\n"
        "Keep the response concise (under 300 words)."
    )
    return _generate(prompt)


def get_medication_info(med_name: str, dosage: str, condition: str) -> str:
    """Return AI-generated patient-friendly information about a medication."""
    prompt = (
        f"Provide a concise patient-friendly summary for:\n"
        f"Medication: {med_name}\n"
        f"Dosage: {dosage}\n"
        f"Prescribed for: {condition}\n\n"
        "Include:\n"
        "1. Purpose and how it works (2 sentences)\n"
        "2. Common side effects to watch for\n"
        "3. Key adherence tips (what to do if a dose is missed, food interactions)\n"
        "4. Warning signs requiring immediate medical attention\n\n"
        "Keep it under 250 words. Use plain language."
    )
    return _generate(prompt)


def generate_reminder_message(med_name: str, dosage: str, patient_name: str) -> str:
    """Generate a friendly, personalised reminder message."""
    prompt = (
        f"Write a warm, motivating medication reminder message for:\n"
        f"Patient: {patient_name}\n"
        f"Medication: {med_name}\n"
        f"Dosage: {dosage}\n\n"
        "The message should:\n"
        "- Be friendly and encouraging (2–3 sentences)\n"
        "- Remind them why adherence matters\n"
        "- Avoid being preachy\n\n"
        "Return ONLY the reminder message, no extra commentary."
    )
    return _generate(prompt)


def summarise_patient_for_doctor(
    patient_name: str,
    conditions: str,
    medications: list[dict],
    stats: dict,
    recent_side_effects: list[str],
) -> str:
    """Generate a clinical-style patient adherence summary for doctors."""
    med_list = "\n".join(
        f"  - {m['name']} {m['dosage']} ({m['frequency']})" for m in medications
    )
    se_text = "; ".join(recent_side_effects) if recent_side_effects else "None reported"
    prompt = (
        f"Generate a concise clinical adherence summary for a physician review:\n\n"
        f"Patient: {patient_name}\n"
        f"Chronic conditions: {conditions}\n"
        f"Active medications:\n{med_list}\n\n"
        f"Adherence (last {stats.get('days', 30)} days):\n"
        f"  - Overall rate: {stats['rate']}%\n"
        f"  - Taken: {stats['taken']}/{stats['total']} doses\n"
        f"  - Missed: {stats['missed']}, Skipped: {stats['skipped']}\n\n"
        f"Recently reported side effects: {se_text}\n\n"
        "Provide:\n"
        "1. Clinical adherence interpretation\n"
        "2. Medication risk assessment\n"
        "3. Recommended follow-up actions\n"
        "4. Any patterns requiring clinical attention\n\n"
        "Use professional medical language. Keep under 300 words."
    )
    return _generate(prompt)


def suggest_adherence_improvements(
    conditions: str,
    medications: list[dict],
    barriers: str,
) -> str:
    """Personalised AI plan to overcome adherence barriers."""
    med_names = ", ".join(m["name"] for m in medications) if medications else "multiple medications"
    prompt = (
        f"A chronic patient with {conditions} is taking {med_names} but struggling with adherence.\n"
        f"Reported barriers: {barriers if barriers else 'not specified'}\n\n"
        "Create a personalised adherence improvement plan:\n"
        "1. Address each reported barrier with a specific strategy\n"
        "2. Suggest technology tools or habit-stacking techniques\n"
        "3. Recommend communication approaches with their healthcare team\n"
        "4. Provide a realistic 7-day starter plan\n\n"
        "Keep it practical, empathetic, and under 350 words."
    )
    return _generate(prompt)
