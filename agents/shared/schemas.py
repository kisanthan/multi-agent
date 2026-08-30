"""Pydantic schemas for the LLM extraction.

These models are the contract between the language model and the
application. They are handed to Ollama as a JSON schema, and the response is
validated against them (llm/extraction.py) -- the field descriptions are
therefore not a comment, but part of the prompt.
"""

from __future__ import annotations

from enum import Enum

from pydantic import BaseModel, Field


class DocumentType(str, Enum):
    PAYMENT_CONFIRMATION = "zahlungsbestaetigung"
    INCOMING_INVOICE = "eingangsrechnung"
    UNKNOWN = "unbekannt"


class DocumentRouting(BaseModel):
    """The shared router decides only which process owns the document."""

    type: DocumentType = Field(
        description="Dokumenttyp. 'zahlungsbestaetigung' = Bank bestaetigt eine "
                    "Zahlung; 'eingangsrechnung' = Lieferant fordert Geld."
    )


class PaymentExtraction(BaseModel):
    number: str | None = Field(
        default=None, description="Rechnungs- oder Bestellnummer im Verwendungszweck."
    )
    amount_eur: float | None = Field(
        default=None, description="Gezahlter Gesamtbetrag in Euro als Zahl."
    )


class InvoiceExtraction(BaseModel):
    number: str | None = Field(default=None, description="Rechnungsnummer.")
    amount_eur: float | None = Field(
        default=None, description="Gesamtbetrag in Euro als Zahl."
    )
    supplier: str | None = Field(default=None, description="Name des Lieferanten.")
    line_items: list[str] = Field(
        default_factory=list, description="Bezeichnungen der Rechnungspositionen."
    )
    cost_center_reference: str | None = Field(
        default=None, description="Kostenstellenreferenz, z.B. KTR-ITINFRA."
    )


class Classification(BaseModel):
    """Legacy combined result retained for stored cases and compatibility."""

    type: DocumentType = Field(
        description="Dokumenttyp. 'zahlungsbestaetigung' = Bank bestaetigt eine "
                    "ausgehende Zahlung. 'eingangsrechnung' = Lieferant fordert Geld."
    )
    number: str | None = Field(
        default=None,
        description="Rechnungs- oder Bestellnummer, z.B. RE-2026-4200 oder "
                    "ER-2026-7101. Bei Zahlungsbestaetigungen steht sie im "
                    "Verwendungszweck.",
    )
    amount_eur: float | None = Field(
        default=None,
        description="Gesamtbetrag in Euro als Zahl. Achtung deutsche Notation: "
                    "'1.341,96' bedeutet 1341.96.",
    )
    supplier: str | None = Field(
        default=None, description="Name des Lieferanten bzw. Zahlungsempfaengers."
    )
    line_items: list[str] = Field(
        default_factory=list,
        description="Nur bei Eingangsrechnungen: die Bezeichnungen der "
                    "Rechnungspositionen, woertlich.",
    )
    cost_center_reference: str | None = Field(
        default=None,
        description="Nur bei Eingangsrechnungen: die auf dem Beleg angegebene "
                    "Kostenstellenreferenz, z.B. KTR-ITINFRA. None, wenn der "
                    "Beleg keine Referenz nennt.",
    )
