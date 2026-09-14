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
        "nicht erreichbar. Die Zahlung wurde nicht verbucht; die Rechnung "
        "bleibt offen."
    ),
}


def approval_inputs(request: dict, *, thread_id: str) -> dict:
    """Process A's approval point needs no input beyond confirm/reject."""
    return {}


def effect_metric(effect: Effect) -> tuple[str, str] | None:
    if effect.navision_status:
        return (i18n.t("payment.invoice", number=effect.navision_number),
                effect.navision_status.capitalize())
    return None
