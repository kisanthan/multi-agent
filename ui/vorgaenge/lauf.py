"""Vorgaenge starten und fortsetzen -- mit sichtbarem Fortschritt.

Blockierend und bewusst so: ein Lauf dauert mit lokalem Modell ein bis drei
Minuten, und in dieser Zeit soll sichtbar sein, was passiert. Ein stummer
Spinner wuerde wie ein Absturz wirken. Die Betriebsgrenze steht in
docs/grenzen.md (L8).
"""

from __future__ import annotations

import uuid
from datetime import datetime, timezone
from pathlib import Path

import streamlit as st


def _stream(app, thread: dict, eingabe, titel: str) -> bool:
    """Faehrt den Graphen und zeigt jeden Knoten, sobald er fertig ist.

    Gibt zurueck, ob der Lauf ohne Ausnahme endete. Ein Fehler wird angezeigt
    statt geworfen: der Vorgang bleibt im Checkpoint und ist danach in der
    Liste sichtbar -- ein Absturz der Seite wuerde ihn nur unauffindbar machen.
    """
    gezeigt = 0
    with st.status(titel, expanded=True) as kasten:
        try:
            for zustand in app.stream(eingabe, thread, stream_mode="values"):
                protokoll = zustand.get("protokoll", []) if isinstance(zustand, dict) else []
                for eintrag in protokoll[gezeigt:]:
                    st.write(f"**{eintrag['knoten']}** — {eintrag['text']}")
                gezeigt = max(gezeigt, len(protokoll))
        except Exception as e:  # noqa: BLE001 - der Nutzer soll den Grund sehen
            kasten.update(label=f"Vorgang abgebrochen: {e}", state="error")
            st.exception(e)
            return False
        kasten.update(label="Verarbeitung beendet", state="complete")
    return True


def starte(app, *, pfad: Path | str, akteur: str, upload_id: str | None = None) -> str:
    """Legt einen Vorgang an und faehrt ihn bis zum ersten Halt."""
    dateiname = Path(pfad).name
    thread_id = f"{dateiname}-{uuid.uuid4().hex[:8]}"

    _stream(app, {"configurable": {"thread_id": thread_id}}, {
        "pfad": str(pfad),
        "akteur": akteur,
        "upload_id": upload_id,
        "vorgang_id": thread_id,
        "gestartet_am": datetime.now(timezone.utc).isoformat(),
        "protokoll": [],
    }, f"Vorgang läuft: {dateiname}")

    return thread_id


def setze_fort(app, *, thread_id: str, antwort: dict) -> None:
    """Setzt einen wartenden Vorgang nach der Entscheidung fort."""
    from langgraph.types import Command

    _stream(app, {"configurable": {"thread_id": thread_id}},
            Command(resume=antwort), "Entscheidung wird verarbeitet")
