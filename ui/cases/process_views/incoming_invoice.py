"""Process B (Eingangsrechnung) fragments of the case-detail view.

Exports the same three names as `payment_confirmation.py`, so
`ui/cases/process_views/__init__.py` can treat both processes identically.
"""

from __future__ import annotations

import streamlit as st

from agents.incoming_invoice import cost_center as cost_center_agent
from graph.effects import Effect
from ui.shared.context import connection

RESULT_TEXTS = {
    "archiviert": "Die Rechnung ist revisionssicher abgelegt. Damit ist der "
                  "Vorgang beendet.",
    "archivierung_fehlgeschlagen": "Die Ablage im Archiv ist fehlgeschlagen.",
}


def approval_inputs(request: dict, *, thread_id: str) -> dict:
    """Lets the approver pick a cost center when the document reference did
    not resolve one. Falls back to a fresh catalog read if the interrupt
    payload did not carry one (kept from the pre-split behavior)."""
    catalog = request.get("catalog") or []
    if not catalog:
        con = connection()
        try:
            catalog = [{"id": z[0], "name": z[1], "reference": z[2]}
                       for z in cost_center_agent.catalog(con)]
        finally:
            con.close()
    labels = {e["id"]: f"{e['id']} — {e['name']} ({e['reference']})"
              for e in catalog}
    st.warning("Auf dem Beleg steht keine Kostenstelle, die zugeordnet "
               "werden konnte. Bitte wählen Sie die passende aus.")
    cost_center_id = st.selectbox(
        "Kostenstelle", [e["id"] for e in catalog],
        format_func=lambda o: labels.get(o, o), key=f"kst_{thread_id}",
    )
    return {"cost_center_id": cost_center_id} if cost_center_id else {}


def effect_metric(effect: Effect) -> tuple[str, str] | None:
    if effect.elo_archive_id:
        return ("Im Archiv abgelegt unter", effect.elo_archive_id)
    return None
