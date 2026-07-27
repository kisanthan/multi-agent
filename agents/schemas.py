"""Pydantic-Schemata fuer die LLM-Extraktion.

Diese Modelle sind der Vertrag zwischen Sprachmodell und Anwendung. Sie werden
Ollama als JSON-Schema uebergeben und die Antwort gegen sie validiert
(llm/extraktion.py) -- die Feldbeschreibungen sind daher kein Kommentar,
sondern Teil des Prompts.
"""

from __future__ import annotations

from enum import Enum

from pydantic import BaseModel, Field


class Dokumenttyp(str, Enum):
    ZAHLUNGSBESTAETIGUNG = "zahlungsbestaetigung"
    EINGANGSRECHNUNG = "eingangsrechnung"
    UNBEKANNT = "unbekannt"


class Klassifikation(BaseModel):
    """Ergebnis des Klassifikations- & Extraktions-Agenten.

    Typ UND Felder in einem Durchgang (Vorgabe des Fachkonzepts). Die Felder
    sind optional, weil sie je nach Dokumenttyp unterschiedlich belegt sind --
    ein Pflichtfeld, das es im Dokument nicht gibt, wuerde das Modell zum
    Erfinden zwingen.
    """

    typ: Dokumenttyp = Field(
        description="Dokumenttyp. 'zahlungsbestaetigung' = Bank bestaetigt eine "
                    "ausgehende Zahlung. 'eingangsrechnung' = Lieferant fordert Geld."
    )
    nummer: str | None = Field(
        default=None,
        description="Rechnungs- oder Bestellnummer, z.B. RE-2026-4200 oder "
                    "ER-2026-7101. Bei Zahlungsbestaetigungen steht sie im "
                    "Verwendungszweck.",
    )
    betrag_eur: float | None = Field(
        default=None,
        description="Gesamtbetrag in Euro als Zahl. Achtung deutsche Notation: "
                    "'1.341,96' bedeutet 1341.96.",
    )
    lieferant: str | None = Field(
        default=None, description="Name des Lieferanten bzw. Zahlungsempfaengers."
    )
    positionen: list[str] = Field(
        default_factory=list,
        description="Nur bei Eingangsrechnungen: die Bezeichnungen der "
                    "Rechnungspositionen, woertlich.",
    )
    kostenstellen_referenz: str | None = Field(
        default=None,
        description="Nur bei Eingangsrechnungen: die auf dem Beleg angegebene "
                    "Kostenstellenreferenz, z.B. KTR-ITINFRA. None, wenn der "
                    "Beleg keine Referenz nennt.",
    )
