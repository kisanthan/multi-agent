"""Beschriftungen und Zahlenformate.

Kennt weder Prozesse noch Streamlit -- nur, wie ein Zustandsfeld fuer einen
Menschen aussehen muss. Rein und damit ohne laufende App pruefbar.
"""

from __future__ import annotations

# Rohe Zustandsschluessel sind fuer einen Sachbearbeiter unlesbar. Diese
# Tabelle ist die einzige Stelle, an der aus 'soll_betrag_eur' etwas
# Vorzeigbares wird.
LABELS = {
    "dateiname": "Beleg",
    "nummer": "Rechnungsnummer",
    "betrag_eur": "Betrag auf dem Beleg",
    "soll_betrag_eur": "Betrag laut Rechnung",
    "lieferant": "Lieferant",
    "referenz": "Kostenstelle auf dem Beleg",
    "kostenstellen_referenz": "Kostenstelle auf dem Beleg",
    "kostenstelle_id": "Zugeordnete Kostenstelle",
    "grund": "Warum",
    "befund": "Prüfergebnis",
    "begruendung": "Erläuterung",
    "eskalation": "Hinweis",
    "positionen": "Rechnungsposten",
    "akteur": "Hochgeladen von",
    "freigegeben_von": "Bestätigt von",
    "archiv_id": "Ablagenummer",
    "typ": "Belegart",
    "gestartet_am": "Eingegangen",
}

BETRAGSFELDER = frozenset({"betrag_eur", "soll_betrag_eur"})


def euro(wert: float | None) -> str:
    """1341.96 -> '1.341,96 €' (deutsche Notation)."""
    if wert is None:
        return "—"
    # Umweg ueber das englische Format: Python kennt kein Locale-freies de-DE.
    formatiert = f"{wert:,.2f}".replace(",", "#").replace(".", ",").replace("#", ".")
    return f"{formatiert} €"


def dateigroesse(bytes_: int | None) -> str:
    """Bytezahl als '1,4 MB'."""
    if not bytes_:
        return "—"
    for einheit, teiler in (("MB", 1024 * 1024), ("kB", 1024)):
        if bytes_ >= teiler:
            return f"{bytes_ / teiler:.1f}".replace(".", ",") + f" {einheit}"
    return f"{bytes_} B"


def zeitpunkt(iso: str | None) -> str:
    """ISO-Zeitstempel auf 'TT.MM.JJJJ, HH:MM' kuerzen."""
    if not iso:
        return "—"
    try:
        datum, rest = iso.split("T")
        jahr, monat, tag = datum.split("-")
        return f"{tag}.{monat}.{jahr}, {rest[:5]}"
    except (ValueError, IndexError):
        return iso


def datum(iso: str | None) -> str:
    """Nur der Tag -- fuer Filter und dichte Tabellen."""
    if not iso:
        return "—"
    try:
        jahr, monat, tag = iso.split("T")[0].split("-")
        return f"{tag}.{monat}.{jahr}"
    except ValueError:
        return iso


def aufzaehlung(teile, *, verbinder: str = "und") -> str:
    """['A', 'B', 'C'] -> 'A, B und C'.

    Damit ein Satz auch dann lesbar bleibt, wenn ein dritter Prozess
    hinzukommt -- fest verdrahtetes „A oder B" waere dann falsch.
    """
    teile = [t for t in teile if t]
    if not teile:
        return ""
    if len(teile) == 1:
        return teile[0]
    return f"{', '.join(teile[:-1])} {verbinder} {teile[-1]}"


def mehrzahl(belegart: str) -> str:
    """Grobe Pluralform der Belegarten.

    Reicht fuer 'Zahlungsbestaetigung' und 'Eingangsrechnung'; kommt eine Art
    mit anderer Endung hinzu, gehoert die Form in die Prozessregistry.
    """
    if belegart.endswith(("ung", "ion", "heit", "keit")):
        return belegart + "en"
    if belegart.endswith("e"):
        return belegart + "n"
    return belegart + "e"


def beschriftung(schluessel: str) -> str:
    return LABELS.get(schluessel, schluessel.replace("_", " ").capitalize())


def feld(schluessel: str, wert) -> tuple[str, str]:
    """Ein Zustandsfeld als (Beschriftung, formatierter Wert)."""
    if schluessel in BETRAGSFELDER:
        return beschriftung(schluessel), euro(wert)
    if schluessel in ("gestartet_am", "hochgeladen_am"):
        return beschriftung(schluessel), zeitpunkt(wert)
    if isinstance(wert, list):
        return beschriftung(schluessel), ", ".join(str(w) for w in wert) if wert else "—"
    return beschriftung(schluessel), "—" if wert in (None, "") else str(wert)
