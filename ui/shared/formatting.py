"""Labels and number formats.

Knows neither processes nor Streamlit -- only what a state field must look
like for a human. Pure, and therefore testable without a running app.

Everything here is language-dependent twice over: the *words* (a field's
label) come from the catalogs in `ui/locales/`, and the *conventions*
(decimal comma, date order) from the branch on the active language below.
An English reader who sees "1.341,96 €" reads a different number than the
one meant, so translating the labels alone would not be enough.
"""

from __future__ import annotations

from ui.shared import i18n

# Raw state keys are unreadable for a case worker. This table is the only
# place where 'expected_amount_eur' becomes something presentable -- and,
# per `ui/shared/i18n.py`, the only home of the German wording: the
# catalogs carry `field.<key>` for the other languages, not a German copy.
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
    """1341.96 -> '1.341,96 €' (de) or '€1,341.96' (en)."""
    if value is None:
        return "—"
    # Detour via the English format: Python has no locale-free de-DE.
    english = f"{value:,.2f}"
    if i18n.language() == "de":
        german = english.replace(",", "#").replace(".", ",").replace("#", ".")
        return f"{german} €"
    return f"€{english}"


def file_size(num_bytes: int | None) -> str:
    """Byte count as '1,4 MB' (de) or '1.4 MB' (en)."""
    if not num_bytes:
        return "—"
    for unit, divisor in (("MB", 1024 * 1024), ("kB", 1024)):
        if num_bytes >= divisor:
            number = f"{num_bytes / divisor:.1f}"
            if i18n.language() == "de":
                number = number.replace(".", ",")
            return f"{number} {unit}"
    return f"{num_bytes} B"


def timestamp(iso: str | None) -> str:
    """Shortens an ISO timestamp to 'DD.MM.YYYY, HH:MM' (de).

    English keeps the ISO date instead of switching to a second
    day/month order: 05.06. and 06/05 are both real dates and the reader
    cannot tell from the string which convention produced it.
    """
    if not iso:
        return "—"
    try:
        date_part, rest = iso.split("T")
        return f"{date_only(date_part)}, {rest[:5]}"
    except (ValueError, IndexError):
        return iso


def date_only(iso: str | None) -> str:
    """Just the day -- for filters and dense tables."""
    if not iso:
        return "—"
    day_part = iso.split("T")[0]
    if i18n.language() != "de":
        return day_part
    try:
        year, month, day = day_part.split("-")
        return f"{day}.{month}.{year}"
    except ValueError:
        return iso


def enumerate_list(parts, *, connector: str | None = None) -> str:
    """['A', 'B', 'C'] -> 'A, B und C'.

    So a sentence stays readable even when a third process is added --
    a hardcoded "A oder B" would then be wrong. Without a connector, the
    active language's "and" is used.
    """
    if connector is None:
        connector = i18n.t("word.and")
    parts = [t for t in parts if t]
    if not parts:
        return ""
    if len(parts) == 1:
        return parts[0]
    return f"{', '.join(parts[:-1])} {connector} {parts[-1]}"


def pluralize(document_kind: str) -> str:
    """Rough plural form of the German document kinds.

    Sufficient for 'Zahlungsbestaetigung' and 'Eingangsrechnung'; if a kind
    with a different ending is added, the form belongs in the process
    registry. Other languages do not build their plural by rule at all --
    they state it outright as `process.<key>.document_kind_plural` (see
    `ui/shared/i18n.py::document_kinds_plural`).
    """
    if document_kind.endswith(("ung", "ion", "heit", "keit")):
        return document_kind + "en"
    if document_kind.endswith("e"):
        return document_kind + "n"
    return document_kind + "e"


def label(key: str) -> str:
    return i18n.t(f"field.{key}",
                  default=LABELS.get(key, key.replace("_", " ").capitalize()))


def field(key: str, value) -> tuple[str, str]:
    """A state field as (label, formatted value)."""
    if key in AMOUNT_FIELDS:
        return label(key), format_euro(value)
    if key in ("started_at", "uploaded_at"):
        return label(key), timestamp(value)
    if isinstance(value, list):
        return label(key), ", ".join(str(w) for w in value) if value else "—"
    return label(key), "—" if value in (None, "") else str(value)
