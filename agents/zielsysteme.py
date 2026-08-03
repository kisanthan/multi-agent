"""ELO-Agent (Prozess B): revisionssichere Archivierung.

Der ELO-Agent ist ein Shared Domain Agent mit Schreibrecht und
Human-on-the-loop. Er bildet das Prozessende von Prozess B (Diagramm Teil 3):
nach der Kostenstellen-Zuordnung wird die Rechnung revisionssicher im DMS
abgelegt -- eine bilanzwirksame Verbuchung findet in Prozess B nicht statt.

Der Agent fragt vor der Schreibaktion die Policy -- eine Freigabe weiter oben im
Prozess (bei Mehrdeutigkeit) ersetzt nicht die Berechtigungspruefung an der
Schreibstelle.
"""

from __future__ import annotations

import sqlite3
from dataclasses import dataclass

import httpx

from config import einstellungen
from governance.audit import OHNE_BEZUG, Entscheidung, Vorgangsbezug, protokolliere
from governance.policy import Ergebnis, pruefe_schreibaktion

ELO_AGENT_ID = "elo"


@dataclass(frozen=True)
class Zielsystemergebnis:
    erfolgreich: bool
    kennung: str | None      # Archiv-ID bzw. Verbindlichkeits-ID
    begruendung: str
    fehler: str | None = None


def _policy_oder_fehler(con: sqlite3.Connection, *, agent_id: str, akteur: str,
                        aktion: str,
                        bezug: Vorgangsbezug = OHNE_BEZUG) -> Zielsystemergebnis | None:
    """Gemeinsame Policy-Pruefung. Gibt None zurueck, wenn erlaubt."""
    entscheid = pruefe_schreibaktion(con, agent_id=agent_id, akteur=akteur, aktion=aktion)
    if entscheid.ergebnis is Ergebnis.ERLAUBT:
        return None

    protokolliere(con, akteur=akteur, agent=agent_id, aktion=aktion,
                  entscheidung=Entscheidung.VERWEIGERT, begruendung=entscheid.begruendung,
                  payload={"regel": entscheid.regel},
                  bezug=bezug, ergebnis="verweigert")
    con.commit()
    return Zielsystemergebnis(False, None, entscheid.begruendung, entscheid.regel)


def archiviere(con: sqlite3.Connection, *, dateiname: str, dokument_hash: str,
               akteur: str, bezug: Vorgangsbezug = OHNE_BEZUG) -> Zielsystemergebnis:
    """ELO-Agent: legt das Dokument revisionssicher ab."""
    if (fehler := _policy_oder_fehler(con, agent_id=ELO_AGENT_ID, akteur=akteur,
                                      aktion="dokument_archivieren", bezug=bezug)):
        return fehler

    try:
        antwort = httpx.post(
            f"{einstellungen.elo_url}/archive",
            json={"dateiname": dateiname, "dokument_hash": dokument_hash,
                  "akteur": akteur, "vorgang_id": bezug.vorgang_id},
            timeout=30.0,
        )
        antwort.raise_for_status()
    except httpx.HTTPError as e:
        return Zielsystemergebnis(False, None, f"ELO nicht erreichbar: {e}", str(e))

    daten = antwort.json()
    hinweis = " (war bereits abgelegt)" if daten.get("bereits_vorhanden") else ""
    return Zielsystemergebnis(
        True, daten["archiv_id"],
        f"Dokument abgelegt unter {daten['archiv_id']}{hinweis}.",
    )
