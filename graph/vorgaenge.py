"""Vorgangsuebersicht: leitet die Fallliste aus dem Checkpoint ab.

LangGraph fuehrt keine Liste laufender Threads -- der Checkpointer kennt sie,
gibt sie aber nicht als Uebersicht heraus. Dieses Modul liest die Thread-IDs
aus der Checkpoint-Datenbank und ermittelt je Thread den fachlichen Status.

Bewusst kein eigener Vorgangs-Tabelle in `stammdaten.db`: der Zustand eines
Vorgangs liegt im Checkpoint, und das ist die Aussage der Arbeit (der Vorgang
ueberlebt den Prozess und wartet dort auf den Menschen). Eine zweite Tabelle
waere eine zweite Wahrheit, die auseinanderlaufen kann.

`status_von()` und `prozess_von()` sind reine Funktionen: sie kennen weder
LangGraph noch Streamlit und sind darum ohne beides pruefbar.
"""

from __future__ import annotations

import sqlite3
from dataclasses import dataclass
from enum import Enum
from pathlib import Path

import prozessregistry


class Status(str, Enum):
    """Fachlicher Status eines Vorgangs -- nicht der technische Graph-Zustand."""

    LAEUFT = "laeuft"
    WARTET_AUF_FREIGABE = "wartet_auf_freigabe"
    ABGESCHLOSSEN = "abgeschlossen"
    VERWORFEN = "verworfen"
    ABGEWIESEN = "abgewiesen"          # AD-Check verweigert (Least Privilege)
    FEHLGESCHLAGEN = "fehlgeschlagen"  # Zielsystem hat abgelehnt

    @property
    def beschriftung(self) -> str:
        """Was auf dem Bildschirm steht.

        Bewusst ohne Fachjargon: der interne Name (`wartet_auf_freigabe`)
        gehoert in Code und Audit-Trail, auf dem Bildschirm steht, was ein
        Sachbearbeiter davon wissen muss.
        """
        return {
            Status.LAEUFT: "In Bearbeitung",
            Status.WARTET_AUF_FREIGABE: "Wartet auf Bestätigung",
            Status.ABGESCHLOSSEN: "Abgeschlossen",
            Status.VERWORFEN: "Abgelehnt",
            Status.ABGEWIESEN: "Nicht berechtigt",
            Status.FEHLGESCHLAGEN: "Fehlgeschlagen",
        }[self]

    @property
    def ist_offen(self) -> bool:
        return self in (Status.LAEUFT, Status.WARTET_AUF_FREIGABE)


def status_von(werte: dict, *, wartet: bool) -> Status:
    """Leitet den fachlichen Status aus dem Vorgangszustand ab.

    `wartet` kommt von aussen (aus `StateSnapshot.interrupts`), damit die
    Funktion rein bleibt und im Test ohne Graph aufgerufen werden kann.

    Ein wartender Vorgang gilt immer als wartend, auch wenn im Zustand noch ein
    alter `ergebnis`-Wert steht: der Interrupt ist die staerkere Aussage --
    dort haengt er gerade, dort muss ein Mensch hin.
    """
    if wartet:
        return Status.WARTET_AUF_FREIGABE

    if not werte.get("abgeschlossen"):
        return Status.LAEUFT

    ergebnis = werte.get("ergebnis")
    # Was als Erfolg gilt, sagt der jeweilige Prozess (prozessregistry), nicht
    # eine Liste hier -- sonst muesste ein dritter Prozess sie ergaenzen.
    if ergebnis in prozessregistry.erfolgreiche_ergebnisse():
        return Status.ABGESCHLOSSEN
    if ergebnis == "verworfen":
        return Status.VERWORFEN
    if ergebnis == "zugriff_verweigert":
        return Status.ABGEWIESEN
    # 'abgelehnt', 'archivierung_fehlgeschlagen' und alles Unerwartete: der
    # Vorgang ist beendet, aber nicht erfolgreich. Kein stiller Erfolg.
    return Status.FEHLGESCHLAGEN


def prozess_von(werte: dict) -> str | None:
    """Prozessschluessel des Vorgangs, oder None.

    Der Dokumenttyp entsteht erst im Klassifikations-Agenten; davor ist der
    Vorgang auf der gemeinsamen Ingestionsstrecke und gehoert noch keinem
    Prozess an.
    """
    konfiguration = prozessregistry.fuer_dokumenttyp(werte.get("typ"))
    return konfiguration.schluessel if konfiguration else None


@dataclass(frozen=True)
class Vorgangsuebersicht:
    """Eine Zeile der Fallliste."""

    thread_id: str
    dateiname: str
    akteur: str
    status: Status
    prozess: str | None
    gestartet_am: str
    ergebnis: str | None
    freigegeben_von: str | None


def thread_ids(checkpoint_pfad: Path | str) -> list[str]:
    """Liest die Thread-IDs aus der Checkpoint-Datenbank.

    Fehlt die Datei oder die Tabelle (noch kein Lauf stattgefunden), ist das
    kein Fehler, sondern eine leere Liste.
    """
    pfad = Path(checkpoint_pfad)
    if not pfad.is_file():
        return []

    con = sqlite3.connect(pfad)
    try:
        return [r[0] for r in con.execute(
            "SELECT DISTINCT thread_id FROM checkpoints"
        ).fetchall()]
    except sqlite3.OperationalError:
        return []
    finally:
        con.close()


def uebersicht(app, checkpoint_pfad: Path | str) -> list[Vorgangsuebersicht]:
    """Alle bekannten Vorgaenge, neueste zuerst.

    Fragt je Thread den Checkpoint ab. Das ist O(n) in der Zahl der Vorgaenge
    und fuer einen Prototyp mit einigen Dutzend Laeufen angemessen; ein
    Produktivsystem haette hier einen Index.
    """
    zeilen = []
    for thread_id in thread_ids(checkpoint_pfad):
        schnappschuss = app.get_state({"configurable": {"thread_id": thread_id}})
        werte = schnappschuss.values or {}
        if not werte:
            continue  # angelegter, aber nie gelaufener Thread

        zeilen.append(Vorgangsuebersicht(
            thread_id=thread_id,
            dateiname=werte.get("dateiname") or Path(werte.get("pfad", "")).name or thread_id,
            akteur=werte.get("akteur", "-"),
            status=status_von(werte, wartet=bool(schnappschuss.interrupts)),
            prozess=prozess_von(werte),
            gestartet_am=werte.get("gestartet_am", ""),
            ergebnis=werte.get("ergebnis"),
            freigegeben_von=werte.get("freigegeben_von"),
        ))

    return sorted(zeilen, key=lambda z: z.gestartet_am, reverse=True)
