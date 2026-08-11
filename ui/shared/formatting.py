"""Labels and number formats.

Knows neither processes nor Streamlit -- only what a state field must look
like for a human. Pure, and therefore testable without a running app.
"""

from __future__ import annotations

# Raw state keys are unreadable for a case worker. This table is the only
# place where 'expected_amount_eur' becomes something presentable.
LABELS = {
    "filename": "Beleg",
    "number": "Rechnungsnummer",
    "amount_eur": "Betrag auf dem Beleg",
    "expected_amount_eur": "Betrag laut Rechnung",
    "supplier": "Lieferant",
    "reference": "Kostenstelle auf dem Beleg",
    "cost_center_reference": "Kostenstelle auf dem Beleg",
    "cost_center_id": "Zugeordnete Kostenstelle",
    "reason": "Warum",
    "finding": "Prüfergebnis",
    "escalation": "Hinweis",
    "line_items": "Rechnungsposten",
    "actor": "Hochgeladen von",
    "approved_by": "Bestätigt von",
    "archive_id": "Ablagenummer",
    "document_type": "Belegart",
    "started_at": "Eingegangen",
}

AMOUNT_FIELDS = frozenset({"amount_eur", "expected_amount_eur"})


def format_euro(value: float | None) -> str:
    """1341.96 -> '1.341,96 €' (German notation)."""
    if value is None:
        return "—"
    # Detour via the English format: Python has no locale-free de-DE.
    formatted = f"{value:,.2f}".replace(",", "#").replace(".", ",").replace("#", ".")
    return f"{formatted} €"


def file_size(num_bytes: int | None) -> str:
    """Byte count as '1,4 MB'."""
    if not num_bytes:
        return "—"
    for unit, divisor in (("MB", 1024 * 1024), ("kB", 1024)):
        if num_bytes >= divisor:
            return f"{num_bytes / divisor:.1f}".replace(".", ",") + f" {unit}"
    return f"{num_bytes} B"


def timestamp(iso: str | None) -> str:
    """Shortens an ISO timestamp to 'DD.MM.YYYY, HH:MM'."""
    if not iso:
        return "—"
    try:
        date_part, rest = iso.split("T")
        year, month, day = date_part.split("-")
        return f"{day}.{month}.{year}, {rest[:5]}"
    except (ValueError, IndexError):
        return iso


def date_only(iso: str | None) -> str:
    """Just the day -- for filters and dense tables."""
    if not iso:
        return "—"
    try:
        year, month, day = iso.split("T")[0].split("-")
        return f"{day}.{month}.{year}"
    except ValueError:
        return iso


def enumerate_list(parts, *, connector: str = "und") -> str:
    """['A', 'B', 'C'] -> 'A, B und C'.

    So a sentence stays readable even when a third process is added --
    a hardcoded "A oder B" would then be wrong.
    """
    parts = [t for t in parts if t]
    if not parts:
        return ""
    if len(parts) == 1:
        return parts[0]
    return f"{', '.join(parts[:-1])} {connector} {parts[-1]}"


def pluralize(document_kind: str) -> str:
    """Rough plural form of the document kinds.

    Sufficient for 'Zahlungsbestaetigung' and 'Eingangsrechnung'; if a kind
    with a different ending is added, the form belongs in the process
    registry.
    """
    if document_kind.endswith(("ung", "ion", "heit", "keit")):
        return document_kind + "en"
    if document_kind.endswith("e"):
        return document_kind + "n"
    return document_kind + "e"


def label(key: str) -> str:
    return LABELS.get(key, key.replace("_", " ").capitalize())


def field(key: str, value) -> tuple[str, str]:
    """A state field as (label, formatted value)."""
    if key in AMOUNT_FIELDS:
        return label(key), format_euro(value)
    if key in ("started_at", "uploaded_at"):
        return label(key), timestamp(value)
    if isinstance(value, list):
        return label(key), ", ".join(str(w) for w in value) if value else "—"
    return label(key), "—" if value in (None, "") else str(value)
