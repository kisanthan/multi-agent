"""Der LangGraph-Workflow: beide Prozesse in einem Graphen.

Bildet die Konzeptdiagramme auf ausfuehrbaren Code ab:
- Jeder Agent = ein Knoten.
- Der Orchestrator = eine Conditional Edge nach Dokumenttyp.
- HITL-Punkte = `interrupt()`; der Checkpointer haelt den Zustand, bis ein
  Mensch entscheidet.
- Policy-Pruefungen liegen in den schreibenden Knoten, vor dem Zielsystemaufruf.
- Jeder Schritt schreibt in den Audit-Trail.

Warum ein Graph fuer beide Prozesse: die Arbeit argumentiert mit *gemeinsamen*
Komponenten (Reader, Orchestrator, Klassifikation, Datenbasis). Zwei getrennte
Graphen wuerden diese Aussage im Code aufloesen.
"""

from __future__ import annotations

import sqlite3
from pathlib import Path

from langgraph.graph import END, START, StateGraph
from langgraph.types import interrupt

from agents import abgleich, buchung, klassifikation, kostenstelle, zielsysteme
from agents.abgleich import Befund
from agents.schemas import Dokumenttyp
from config import DB_PFAD
from governance.audit import Entscheidung, protokolliere
from graph.state import Vorgang
from tools.reader import ZugriffVerweigert, lies_dokument


def _con() -> sqlite3.Connection:
    return sqlite3.connect(DB_PFAD)


def _notiz(zustand: Vorgang, knoten: str, text: str) -> list[dict]:
    """Haengt einen Schritt an das Laufprotokoll (fuer UI und CLI-Ausgabe)."""
    return [*zustand.get("protokoll", []), {"knoten": knoten, "text": text}]


# --------------------------------------------------------------- Knoten

def knoten_reader(zustand: Vorgang) -> dict:
    """Reader-Tool. Der AD-Check steckt in `lies_dokument` (Least Privilege)."""
    con = _con()
    try:
        inhalt = lies_dokument(con, zustand["pfad"], akteur=zustand["akteur"])
    except ZugriffVerweigert as e:
        # Szenario 5: Ende des Vorgangs. Kein Parsing, kein Modell, kein Ziel.
        return {
            "abgeschlossen": True,
            "ergebnis": "zugriff_verweigert",
            "fehler": str(e),
            "protokoll": _notiz(zustand, "reader", f"AD-Check verweigert: {e}"),
        }
    finally:
        con.close()

    return {
        "markdown": inhalt.markdown,
        "dokument_hash": inhalt.dokument_hash,
        "dateiname": inhalt.dateiname,
        "protokoll": _notiz(zustand, "reader",
                            f"{inhalt.dateiname} gelesen ({inhalt.parser}, "
                            f"{inhalt.seiten} Seite(n))."),
    }


def knoten_klassifikation(zustand: Vorgang) -> dict:
    """Klassifikations- & Extraktions-Agent: Typ und Felder in einem Durchgang."""
    con = _con()
    try:
        e = klassifikation.klassifiziere(con, markdown=zustand["markdown"],
                                         akteur=zustand["akteur"])
    finally:
        con.close()

    if not e.gelungen:
        # R1: Modell haelt das Schema nicht ein -> Klaerfall statt Raten.
        return {
            "klaerfall": True,
            "klaerfall_grund": e.eskalation or "Extraktion fehlgeschlagen",
            "eskalation": e.eskalation,
            "typ": Dokumenttyp.UNBEKANNT.value,
            "protokoll": _notiz(zustand, "klassifikation",
                                f"Extraktion gescheitert -> Klaerfall. {e.eskalation}"),
        }

    d = e.daten
    return {
        "typ": d.typ.value,
        "nummer": d.nummer,
        "betrag_eur": d.betrag_eur,
        "lieferant": d.lieferant,
        "positionen": d.positionen,
        "protokoll": _notiz(zustand, "klassifikation",
                            f"Typ={d.typ.value}, Nummer={d.nummer}, "
                            f"Betrag={d.betrag_eur} ({e.anbieter}/{e.modell}, "
                            f"Versuch {e.versuche})."),
    }


def route_dokumenttyp(zustand: Vorgang) -> str:
    """Orchestrator-Agent: Conditional Edge nach Dokumenttyp.

    Kein Modellaufruf: der Typ steht bereits fest (der Klassifikations-Agent
    hat ihn bestimmt). Der Orchestrator *routet* danach -- ihn erneut ein
    Modell fragen zu lassen, waere ein zweiter Aufruf mit
    Widerspruchspotenzial.
    """
    if zustand.get("abgeschlossen"):
        return "ende"
    if zustand.get("klaerfall"):
        return "hitl"
    typ = zustand.get("typ")
    if typ == Dokumenttyp.ZAHLUNGSBESTAETIGUNG.value:
        return "prozess_a"
    if typ == Dokumenttyp.EINGANGSRECHNUNG.value:
        return "prozess_b"
    return "hitl"


# ---------------------------------------------------------- Prozess A

def knoten_abgleich(zustand: Vorgang) -> dict:
    """Abgleich-Agent (Stufe 1). Deterministisch -- siehe agents/abgleich.py."""
    con = _con()
    try:
        e = abgleich.gleiche_ab(con, nummer=zustand.get("nummer"),
                                betrag_eur=zustand.get("betrag_eur"),
                                akteur=zustand["akteur"])
    finally:
        con.close()

    return {
        "befund": e.befund.value,
        "nummer": e.nummer,
        "soll_betrag_eur": e.soll_betrag_eur,
        "klaerfall": e.ist_klaerfall,
        "klaerfall_grund": e.begruendung if e.ist_klaerfall else "",
        "protokoll": _notiz(zustand, "abgleich", e.begruendung),
    }


def route_abgleich(zustand: Vorgang) -> str:
    return "hitl" if zustand.get("klaerfall") else "buchung"


def knoten_buchung(zustand: Vorgang) -> dict:
    """Buchungs-Agent (Stufe 3). Fragt die Policy -- die entscheidet ueber HITL."""
    con = _con()
    try:
        e = buchung.buche(
            con, nummer=zustand["nummer"], betrag_eur=zustand["betrag_eur"],
            akteur=zustand["akteur"], beleg=zustand["dateiname"],
            freigegeben_von=zustand.get("freigegeben_von"),
        )
    finally:
        con.close()

    if e.freigabe_noetig:
        return {
            "klaerfall": True,
            "klaerfall_grund": e.begruendung,
            "protokoll": _notiz(zustand, "buchung",
                                f"Freigabe erforderlich: {e.begruendung}"),
        }

    return {
        "abgeschlossen": True,
        "ergebnis": "verbucht" if e.gebucht else "abgelehnt",
        "fehler": e.fehler,
        "protokoll": _notiz(zustand, "buchung", e.begruendung),
    }


def route_buchung(zustand: Vorgang) -> str:
    """Nach dem Buchungsversuch: entweder fertig oder Freigabe noetig."""
    if zustand.get("abgeschlossen"):
        return "ende"
    return "hitl"


# ---------------------------------------------------------- Prozess B

def knoten_kostenstelle(zustand: Vorgang) -> dict:
    """Kostenstellen-Agent (Stufe 2): schlaegt vor, fuehrt nichts aus."""
    con = _con()
    try:
        e = kostenstelle.schlage_vor(con, lieferant=zustand.get("lieferant"),
                                     positionen=zustand.get("positionen", []),
                                     akteur=zustand["akteur"])
        if not e.gelungen:
            return {
                "klaerfall": True,
                "klaerfall_grund": e.eskalation or "Vorschlag fehlgeschlagen",
                "eskalation": e.eskalation,
                "protokoll": _notiz(zustand, "kostenstelle",
                                    f"Vorschlag gescheitert -> Klaerfall."),
            }

        d = e.daten
        gueltig = kostenstelle.ist_gueltig(con, d.kostenstelle_id)
    finally:
        con.close()

    # Ein Vorschlag ausserhalb des Katalogs ist unbrauchbar -- nicht der Mensch
    # soll die Halluzination bemerken, sondern das System.
    if d.kostenstelle_id and not gueltig:
        return {
            "kostenstelle_id": None,
            "kostenstelle_begruendung": d.begruendung,
            "kostenstelle_eindeutig": False,
            "kostenstelle_alternativen": d.alternativen,
            "protokoll": _notiz(zustand, "kostenstelle",
                                f"Vorschlag {d.kostenstelle_id} existiert nicht im "
                                "Katalog -- Entscheidung geht an den Menschen."),
        }

    return {
        "kostenstelle_id": d.kostenstelle_id,
        "kostenstelle_begruendung": d.begruendung,
        "kostenstelle_eindeutig": d.eindeutig and gueltig,
        "kostenstelle_alternativen": d.alternativen,
        "protokoll": _notiz(zustand, "kostenstelle",
                            f"Vorschlag: {d.kostenstelle_id} "
                            f"(eindeutig={d.eindeutig}). {d.begruendung}"),
    }


def route_kostenstelle(zustand: Vorgang) -> str:
    """Zuordnung eindeutig? (Diagramm Teil 3).

    Der Kostenstellen-Agent ist Human-on-the-loop: bei eindeutiger Zuordnung
    laeuft der Vorgang automatisch zur Archivierung. Nur bei Mehrdeutigkeit (oder
    fehlgeschlagenem Vorschlag) greift die Vier-Augen-Freigabe. Das spiegelt die
    Struktur von Prozess A (Nummer vorhanden? -> direkt oder Klaerfall).
    """
    if zustand.get("kostenstelle_eindeutig"):
        return "elo"
    return "freigabe"


def knoten_freigabe_kostenstelle(zustand: Vorgang) -> dict:
    """HITL-Punkt Prozess B: Vier-Augen-Freigabe bei Mehrdeutigkeit.

    Wird nur erreicht, wenn die Zuordnung NICHT eindeutig ist (Klaerfall). Bei
    eindeutiger Zuordnung ueberspringt route_kostenstelle diesen Knoten -- der
    Kostenstellen-Agent ist Human-on-the-loop.
    """
    antwort = interrupt({
        "art": "kostenstellen_freigabe",
        "dateiname": zustand.get("dateiname"),
        "lieferant": zustand.get("lieferant"),
        "betrag_eur": zustand.get("betrag_eur"),
        "positionen": zustand.get("positionen", []),
        "vorschlag": zustand.get("kostenstelle_id"),
        "begruendung": zustand.get("kostenstelle_begruendung"),
        "alternativen": zustand.get("kostenstelle_alternativen", []),
        "eindeutig": zustand.get("kostenstelle_eindeutig"),
    })

    con = _con()
    try:
        protokolliere(
            con, akteur=antwort["pruefer"], agent="kostenstelle",
            aktion="kostenstelle_freigegeben",
            entscheidung=(Entscheidung.ERLAUBT if antwort["entscheidung"] == "freigegeben"
                          else Entscheidung.VERWEIGERT),
            begruendung=f"{antwort['pruefer']} hat "
                        f"{antwort.get('kostenstelle_id')} {antwort['entscheidung']}.",
            payload={"kostenstelle_id": antwort.get("kostenstelle_id"),
                     "vorschlag_agent": zustand.get("kostenstelle_id")},
        )
        con.commit()
    finally:
        con.close()

    if antwort["entscheidung"] != "freigegeben":
        return {
            "abgeschlossen": True,
            "ergebnis": "verworfen",
            "freigegeben_von": antwort["pruefer"],
            "protokoll": _notiz(zustand, "freigabe",
                                f"{antwort['pruefer']} hat verworfen."),
        }

    return {
        "kostenstelle_id": antwort["kostenstelle_id"],
        "freigegeben_von": antwort["pruefer"],
        "freigabe_entscheidung": "freigegeben",
        "protokoll": _notiz(zustand, "freigabe",
                            f"{antwort['pruefer']} hat {antwort['kostenstelle_id']} "
                            "freigegeben."),
    }


def route_freigabe_kostenstelle(zustand: Vorgang) -> str:
    return "ende" if zustand.get("abgeschlossen") else "elo"


def knoten_elo(zustand: Vorgang) -> dict:
    """ELO-Agent (Stufe 3): revisionssichere Ablage. Prozessende von Prozess B.

    Nach dem Diagramm Teil 3 endet Prozess B hier -- eine bilanzwirksame
    Verbuchung in Navision findet in Prozess B nicht statt. Navision (NAV) wird
    nur noch in Prozess A angesprochen (Buchungs-Agent, offen -> bezahlt).
    """
    con = _con()
    try:
        e = zielsysteme.archiviere(con, dateiname=zustand["dateiname"],
                                   dokument_hash=zustand["dokument_hash"],
                                   akteur=zustand["akteur"])
    finally:
        con.close()

    if not e.erfolgreich:
        return {
            "abgeschlossen": True,
            "ergebnis": "archivierung_fehlgeschlagen",
            "fehler": e.fehler,
            "protokoll": _notiz(zustand, "elo", e.begruendung),
        }
    return {
        "abgeschlossen": True,
        "ergebnis": "archiviert",
        "archiv_id": e.kennung,
        "protokoll": _notiz(zustand, "elo",
                            f"{e.begruendung} Prozessende Prozess B."),
    }


# ------------------------------------------------------------ HITL A

def knoten_klaerfall(zustand: Vorgang) -> dict:
    """HITL-Punkt Prozess A: Klaerfall oder Buchungsfreigabe.

    Deckt beide Faelle ab, weil sie dieselbe Frage an denselben Menschen
    stellen: 'Diesen Vorgang trotzdem verbuchen?' Der Grund steht im Payload.
    """
    antwort = interrupt({
        "art": "klaerfall",
        "dateiname": zustand.get("dateiname"),
        "grund": zustand.get("klaerfall_grund"),
        "befund": zustand.get("befund"),
        "nummer": zustand.get("nummer"),
        "betrag_eur": zustand.get("betrag_eur"),
        "soll_betrag_eur": zustand.get("soll_betrag_eur"),
        "eskalation": zustand.get("eskalation"),
    })

    if antwort["entscheidung"] != "freigegeben":
        con = _con()
        try:
            protokolliere(con, akteur=antwort["pruefer"], agent="buchung",
                          aktion="klaerfall_entschieden",
                          entscheidung=Entscheidung.VERWEIGERT,
                          begruendung=f"{antwort['pruefer']} hat den Vorgang verworfen.",
                          payload={"nummer": zustand.get("nummer")})
            con.commit()
        finally:
            con.close()
        return {
            "abgeschlossen": True,
            "ergebnis": "verworfen",
            "freigegeben_von": antwort["pruefer"],
            "protokoll": _notiz(zustand, "klaerfall",
                                f"{antwort['pruefer']} hat verworfen."),
        }

    # Der Pruefer darf die Nummer korrigieren (Fall 'unbekannte Nummer').
    return {
        "nummer": antwort.get("nummer") or zustand.get("nummer"),
        "freigegeben_von": antwort["pruefer"],
        "freigabe_entscheidung": "freigegeben",
        "klaerfall": False,
        "protokoll": _notiz(zustand, "klaerfall",
                            f"{antwort['pruefer']} hat freigegeben."),
    }


def route_klaerfall(zustand: Vorgang) -> str:
    if zustand.get("abgeschlossen"):
        return "ende"
    # Nach der Freigabe zurueck in den passenden Prozess. Ein Klaerfall kann
    # auch aus einer fehlgeschlagenen Klassifikation einer Eingangsrechnung
    # entstehen -- dann darf nicht faelschlich eine Zahlung gebucht werden.
    if zustand.get("typ") == Dokumenttyp.EINGANGSRECHNUNG.value:
        return "kostenstelle"
    return "buchung"


# --------------------------------------------------------------- Graph

def baue_graph():
    """Setzt den Graphen zusammen. Ohne Checkpointer -- den setzt der Aufrufer."""
    g = StateGraph(Vorgang)

    g.add_node("reader", knoten_reader)
    g.add_node("klassifikation", knoten_klassifikation)
    g.add_node("abgleich", knoten_abgleich)
    g.add_node("buchung", knoten_buchung)
    g.add_node("klaerfall", knoten_klaerfall)
    g.add_node("kostenstelle", knoten_kostenstelle)
    g.add_node("freigabe_kostenstelle", knoten_freigabe_kostenstelle)
    g.add_node("elo", knoten_elo)

    g.add_edge(START, "reader")

    # Szenario 5 endet direkt nach dem Reader.
    g.add_conditional_edges(
        "reader",
        lambda z: "ende" if z.get("abgeschlossen") else "klassifikation",
        {"ende": END, "klassifikation": "klassifikation"},
    )

    # Orchestrator-Routing nach Dokumenttyp.
    g.add_conditional_edges(
        "klassifikation", route_dokumenttyp,
        {"prozess_a": "abgleich", "prozess_b": "kostenstelle",
         "hitl": "klaerfall", "ende": END},
    )

    # Prozess A
    g.add_conditional_edges("abgleich", route_abgleich,
                            {"hitl": "klaerfall", "buchung": "buchung"})
    g.add_conditional_edges("buchung", route_buchung,
                            {"hitl": "klaerfall", "ende": END})
    g.add_conditional_edges("klaerfall", route_klaerfall,
                            {"buchung": "buchung", "kostenstelle": "kostenstelle",
                             "ende": END})

    # Prozess B -- endet bei ELO (Diagramm Teil 3).
    # Eindeutige Zuordnung laeuft automatisch zur Archivierung; nur bei
    # Mehrdeutigkeit die Vier-Augen-Freigabe.
    g.add_conditional_edges("kostenstelle", route_kostenstelle,
                            {"elo": "elo", "freigabe": "freigabe_kostenstelle"})
    g.add_conditional_edges("freigabe_kostenstelle", route_freigabe_kostenstelle,
                            {"elo": "elo", "ende": END})
    g.add_edge("elo", END)

    return g


def kompiliere(checkpoint_pfad: Path | str | None = None):
    """Kompiliert den Graphen mit SQLite-Checkpointer.

    Der Checkpointer ist nicht optional: ohne ihn kann `interrupt()` den Zustand
    nicht halten und es gaebe kein Human-in-the-loop.
    """
    from langgraph.checkpoint.sqlite import SqliteSaver

    from config import CHECKPOINT_PFAD

    pfad = Path(checkpoint_pfad or CHECKPOINT_PFAD)
    con = sqlite3.connect(pfad, check_same_thread=False)
    return baue_graph().compile(checkpointer=SqliteSaver(con)), con
