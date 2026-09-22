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
    "dublette_geschlossen": (
        "Der Vorgang wurde als Dublette geschlossen. Es wurde keine erneute Buchung ausgeführt."
    ),
    "buchungssystem_nicht_erreichbar": (
        "Die Freigabe wurde erteilt, aber das Buchungssystem Navision war "
        "nicht erreichbar. Der Ausführungsbeleg muss vor einer Wiederholung geprüft werden."
    ),
}


def approval_inputs(request: dict, *, thread_id: str) -> dict:
    """Show the exact posting target and make duplicate handling explicit."""
    import streamlit as st
    duplicate = request.get("finding") == "bereits_bezahlt"
    if duplicate:
        st.error(
            "Eine erneute Buchung ist gesperrt: Der Posten ist bereits als bezahlt erfasst. "
            "Schließen Sie die Dublette oder korrigieren Sie die Daten und lassen Sie sie erneut prüfen."
        )
    elif request.get("trigger") == "aufsichtsmodus":
        st.info(
            "Mit der Freigabe wird genau der unten angezeigte Buchungsvorschlag zur Ausführung freigegeben."
        )

    expected = request.get("expected_amount_eur")
    if request.get("current_status") or expected is not None:
        left, right = st.columns(2)
        with left:
            st.metric("Status im Buchungssystem", request.get("current_status") or "unbekannt")
        with right:
            st.metric("Erwarteter Betrag", f"{expected:.2f} EUR" if expected is not None else "unbekannt")

    number = st.text_input("Rechnungsnummer", value=request.get("number") or "",
                           key=f"payment_number_{thread_id}_{request.get('version', 0)}")
    amount = st.number_input("Zahlbetrag (EUR)", min_value=0.01,
                             value=float(request.get("amount_eur") or .01), step=.01,
                             key=f"payment_amount_{thread_id}_{request.get('version', 0)}")
    st.caption("Korrekturen werden erneut geprüft und müssen anschließend bestätigt werden.")
    changed = (
        number != (request.get("number") or "")
        or round(float(amount), 2) != round(float(request.get("amount_eur") or .01), 2)
    )
    return {"number": number, "amount_eur": amount, "_changed": changed}


def decision_actions(request: dict, values: dict) -> dict:
    """Business-specific button semantics for booking and exception cases."""
    duplicate = request.get("finding") == "bereits_bezahlt"
    changed = bool(values.get("_changed"))
    if duplicate:
        return {
            "confirm": "Korrigierte Daten erneut prüfen",
            "reject": "Als Dublette schließen",
            "confirm_disabled": not changed,
            "reject_confirmation": (
                "Der Vorgang wird ohne Buchung als Dublette geschlossen. "
                "Zum Fortfahren erneut auf „Als Dublette schließen“ klicken."
            ),
            "approve_reason": "Korrigierte Daten zur erneuten Prüfung eingereicht.",
            "reject_reason": "Als Dublette geschlossen; keine Buchung ausgeführt.",
        }
    if changed or request.get("trigger") != "aufsichtsmodus":
        return {
            "confirm": "Daten erneut prüfen",
            "reject": "Vorgang ablehnen",
            "approve_reason": "Korrigierte Daten zur erneuten Prüfung eingereicht.",
            "reject_reason": "Ausnahmefall fachlich abgelehnt.",
        }
    return {
        "confirm": "Buchung freigeben",
        "reject": "Buchung ablehnen",
        "approve_reason": "Angezeigten Buchungsvorschlag geprüft und freigegeben.",
        "reject_reason": "Buchungsvorschlag fachlich abgelehnt.",
    }


def effect_metric(effect: Effect) -> tuple[str, str] | None:
    if effect.navision_status:
        return (i18n.t("payment.invoice", number=effect.navision_number),
                effect.navision_status.capitalize())
    return None
