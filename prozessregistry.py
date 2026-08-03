"""Die Prozesse des Fachkonzepts als wirksame Konfigurationstabelle.

Gegenstueck zu `registry.py`: dort steht, *wer* handelt (Agenten, Rollen,
Aufsicht), hier steht, *worin* gehandelt wird (Prozess A Zahlungseingang,
Prozess B Eingangsrechnung).

Dieses Modul liegt bewusst auf oberster Ebene und nicht in `ui/`. Die
Schrittfolge eines Prozesses ist Fachwissen, kein Darstellungsdetail -- lag sie
in der Oberflaeche, muesste man fuer einen dritten Prozess die Oberflaeche
anfassen. So gilt: **ein weiterer Prozess = ein Eintrag hier plus die Knoten im
Graphen.** Seite, Navigation, Liste, Stepper und Filter entstehen daraus.

Reine Konfiguration ohne Verhalten, ohne LLM-Bezug und ohne Streamlit-Import.
"""

from __future__ import annotations

from dataclasses import dataclass

from agents.schemas import Dokumenttyp


@dataclass(frozen=True)
class Prozessschritt:
    """Ein Schritt im Ablauf.

    `knoten` ist der Knotenname aus `graph/workflow.py`. Er ist der Schluessel,
    ueber den die Oberflaeche im Laufprotokoll nachsieht, ob der Schritt schon
    stattgefunden hat -- die Verbindung zwischen Ablaufmodell und Anzeige.
    """

    knoten: str
    titel: str
    agent_id: str | None


# Die gemeinsame Ingestionsstrecke beider Prozesse (Fachkonzept: geteilter
# Reader, geteilter Klassifikations-Agent, gemeinsame Datenbasis).
GEMEINSAME_SCHRITTE: tuple[Prozessschritt, ...] = (
    Prozessschritt("reader", "Beleg einlesen", "reader"),
    Prozessschritt("klassifikation", "Beleg auswerten", "klassifikation"),
)


@dataclass(frozen=True)
class Prozesskonfiguration:
    schluessel: str          # 'A' | 'B' -- die Kurzbezeichnung der Arbeit
    route: str               # URL-Pfad; einstufig, Streamlit erlaubt kein '/'
    bezeichnung: str         # Name des Prozesses ('Zahlungseingang')
    belegart: str            # Name des Dokuments ('Zahlungsbestätigung')
    icon: str
    beschreibung: str
    dokumenttyp: Dokumenttyp     # entscheidet die Zuordnung eines Vorgangs
    eigene_schritte: tuple[Prozessschritt, ...]
    listenspalten: tuple[str, ...]   # Zustandsfelder fuer die Vorgangsliste
    detailfelder: tuple[str, ...]    # Zustandsfelder fuer den Kopf der Detailseite
    zielsystem: str
    prozessende: str
    abschluss_ergebnis: str      # `ergebnis`-Wert eines erfolgreichen Laufs

    @property
    def schritte(self) -> tuple[Prozessschritt, ...]:
        return (*GEMEINSAME_SCHRITTE, *self.eigene_schritte)


PROZESSE: dict[str, Prozesskonfiguration] = {
    "A": Prozesskonfiguration(
        schluessel="A",
        route="zahlungsbestaetigung",
        bezeichnung="Zahlungsbestätigung",
        belegart="Zahlungsbestätigung",
        icon="💶",
        beschreibung="Eine Zahlungsbestätigung wird eingelesen und mit den "
        "offenen Rechnungen abgeglichen. Nach der Bestätigung durch eine "
        "Person wird die Zahlung verbucht: die Rechnung gilt als bezahlt.",
        dokumenttyp=Dokumenttyp.ZAHLUNGSBESTAETIGUNG,
        eigene_schritte=(
            Prozessschritt("abgleich", "Mit Rechnungsdaten abgleichen", "abgleich"),
            Prozessschritt("klaerfall", "Bestätigung durch eine Person", "buchung"),
            Prozessschritt("buchung", "Zahlung verbuchen", "buchung"),
        ),
        listenspalten=("nummer", "betrag_eur"),
        detailfelder=("nummer", "betrag_eur", "soll_betrag_eur", "befund"),
        zielsystem="Buchhaltung (Navision)",
        prozessende="Die Rechnung ist als bezahlt verbucht",
        abschluss_ergebnis="verbucht",
    ),
    "B": Prozesskonfiguration(
        schluessel="B",
        route="eingangsrechnung",
        bezeichnung="Eingangsrechnung",
        belegart="Eingangsrechnung",
        icon="🧾",
        beschreibung="Eine Eingangsrechnung wird eingelesen und anhand der "
        "Kostenstelle auf dem Beleg zugeordnet. Anschließend wird sie "
        "revisionssicher archiviert. Eine Zahlung wird hier nicht gebucht.",
        dokumenttyp=Dokumenttyp.EINGANGSRECHNUNG,
        eigene_schritte=(
            Prozessschritt("kostenstelle", "Kostenstelle zuordnen", "kostenstelle"),
            Prozessschritt("freigabe", "Bestätigung durch eine Person", "kostenstelle"),
            Prozessschritt("elo", "Rechnung archivieren", "elo"),
        ),
        listenspalten=("lieferant", "betrag_eur"),
        detailfelder=("lieferant", "betrag_eur", "kostenstellen_referenz",
                      "kostenstelle_id"),
        zielsystem="Archiv (ELO)",
        prozessende="Die Rechnung ist revisionssicher archiviert",
        abschluss_ergebnis="archiviert",
    ),
}


def konfiguration(schluessel: str) -> Prozesskonfiguration:
    """Konfiguration eines Prozesses. Unbekannt = Programmierfehler."""
    try:
        return PROZESSE[schluessel]
    except KeyError:
        raise KeyError(
            f"Unbekannter Prozess {schluessel!r}. Bekannt: {sorted(PROZESSE)}"
        ) from None


def fuer_dokumenttyp(typ: str | None) -> Prozesskonfiguration | None:
    """Ordnet einen Dokumenttyp seinem Prozess zu.

    `None`, solange der Typ nicht feststeht (der Klassifikations-Agent hat noch
    nicht gearbeitet) oder unbekannt ist -- dann gehoert der Vorgang noch keinem
    Prozess an, sondern der gemeinsamen Ingestionsstrecke.
    """
    if not typ:
        return None
    return next((p for p in PROZESSE.values() if p.dokumenttyp.value == typ), None)


def fuer_route(route: str) -> Prozesskonfiguration | None:
    return next((p for p in PROZESSE.values() if p.route == route), None)


def alle() -> list[Prozesskonfiguration]:
    """Alle Prozesse in stabiler Reihenfolge (fuer Navigation und Filter)."""
    return [PROZESSE[s] for s in sorted(PROZESSE)]


def belegarten() -> list[str]:
    """Die Dokumentarten, die das System verarbeitet.

    Aus der Registry und nicht als feste Liste im Text: kommt ein Prozess
    hinzu, nennt ihn die Oberflaeche von selbst mit.
    """
    return [p.belegart for p in alle()]


def belegart_fuer(schluessel: str | None) -> str | None:
    """Die Dokumentart eines Prozesses ('Zahlungsbestaetigung')."""
    return konfiguration(schluessel).belegart if schluessel else None


def erfolgreiche_ergebnisse() -> frozenset[str]:
    """Alle `ergebnis`-Werte, die einen fachlich erfolgreichen Abschluss meinen."""
    return frozenset(p.abschluss_ergebnis for p in PROZESSE.values())


def schritt_titel(knoten: str) -> str:
    """Lesbare Bezeichnung eines Graph-Knotens.

    Das Laufprotokoll haelt technische Knotennamen fest (`reader`,
    `klassifikation`). Auf dem Bildschirm haben sie nichts verloren -- dort
    steht, was der Schritt fachlich bedeutet.
    """
    for schritt in (*GEMEINSAME_SCHRITTE,
                    *(s for p in PROZESSE.values() for s in p.eigene_schritte)):
        if schritt.knoten == knoten:
            return schritt.titel
    return knoten.replace("_", " ").capitalize()
