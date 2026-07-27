"""Zustandsmodell des Workflows.

LangGraph fuehrt diesen Zustand ueber alle Knoten und persistiert ihn im
Checkpointer. Genau das macht die HITL-Unterbrechung moeglich: der Vorgang
haelt an einem Freigabepunkt an, der Zustand ueberlebt den Prozess, und ein
Mensch setzt ihn Stunden spaeter fort.
"""

from __future__ import annotations

from typing import Any, TypedDict


class Vorgang(TypedDict, total=False):
    """Ein Dokumentendurchlauf durch Prozess A oder B."""

    # --- Eingang ---
    pfad: str
    akteur: str            # UPN des Einspeisers
    dateiname: str

    # --- Reader ---
    markdown: str
    dokument_hash: str

    # --- Klassifikation ---
    typ: str               # 'zahlungsbestaetigung' | 'eingangsrechnung' | 'unbekannt'
    nummer: str | None
    betrag_eur: float | None
    lieferant: str | None
    positionen: list[str]
    kostenstellen_referenz: str | None   # vom Beleg extrahiert (Prozess B)

    # --- Prozess A: Abgleich ---
    befund: str
    soll_betrag_eur: float | None

    # --- Prozess B: Kostenstelle ---
    kostenstelle_id: str | None
    kostenstelle_begruendung: str
    kostenstelle_eindeutig: bool
    archiv_id: str | None

    # --- HITL ---
    freigegeben_von: str | None
    freigabe_entscheidung: str        # 'freigegeben' | 'verworfen'
    klaerfall: bool
    klaerfall_grund: str

    # --- Ergebnis ---
    abgeschlossen: bool
    ergebnis: str
    fehler: str | None
    eskalation: str | None

    # --- Nachvollziehbarkeit ---
    protokoll: list[dict[str, Any]]
