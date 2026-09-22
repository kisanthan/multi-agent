"""Process A (Zahlungsbestätigung) fragments of the case-detail view.

Exports the same three names as `incoming_invoice.py`, so
`ui/cases/process_views/__init__.py` can treat both processes identically.
"""

from __future__ import annotations

from graph.effects import Effect
from ui.shared import i18n

RESULT_TEXTS = {
    "verbucht": "Die Zahlung ist verbucht. Die Rechnung gilt als bezahlt.",
    "abgelehnt": "Die Buchhaltung hat die Buchung abgelehnt.",
    "buchungssystem_nicht_erreichbar": (
        "Die Freigabe wurde erteilt, aber das Buchungssystem Navision war "
        "nicht erreichbar. Der Ausführungsbeleg muss vor einer Wiederholung geprüft werden."
    ),
}


def approval_inputs(request: dict, *, thread_id: str) -> dict:
    """Process A's approval point needs no input beyond confirm/reject."""
    import streamlit as st
    number = st.text_input("Rechnungsnummer", value=request.get("number") or "",
                           key=f"payment_number_{thread_id}_{request.get('version', 0)}")
    amount = st.number_input("Zahlbetrag (EUR)", min_value=0.01,
                             value=float(request.get("amount_eur") or .01), step=.01,
                             key=f"payment_amount_{thread_id}_{request.get('version', 0)}")
    st.caption("Korrekturen werden erneut geprüft und müssen anschließend bestätigt werden.")
    return {"number": number, "amount_eur": amount}


def effect_metric(effect: Effect) -> tuple[str, str] | None:
    if effect.navision_status:
        return (i18n.t("payment.invoice", number=effect.navision_number),
                effect.navision_status.capitalize())
    return None
