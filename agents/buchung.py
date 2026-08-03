"""Buchungs-Agent (Shared Domain, Stufe 3 = reversibles Schreiben), Prozess A.

Verbucht die Zahlung im ERP und setzt den Status offen -> bezahlt.

Der finanzwirksame Buchungsschritt steht unter Human-in-the-loop (Thesis §7.4):
jede Buchung erfordert eine menschliche Freigabe -- unabhaengig vom Betrag. Der
Agent entscheidet das nicht selbst, sondern *fragt die Policy*
(governance/policy.py). Das ist der Kern der Architekturaussage: die Governance
sitzt nicht im Agenten und erst recht nicht im Modell.

Der Agent ruft selbst kein Sprachmodell auf. Was hier passiert -- Policy fragen,
HTTP-Call ans ERP -- ist deterministisch. Die Modellklasse FRONTIER in der
Registry bleibt dennoch korrekt: sie beschreibt die *Risikoklasse* der Rolle
und steuert, welches Modell ein Agent dieser Stufe bekaeme.
"""

from __future__ import annotations

import sqlite3
from dataclasses import dataclass

import httpx

from config import einstellungen
from governance.audit import OHNE_BEZUG, Entscheidung, Vorgangsbezug, protokolliere
from governance.policy import Ergebnis, pruefe_schreibaktion

AGENT_ID = "buchung"


@dataclass(frozen=True)
class Buchungsergebnis:
    gebucht: bool
    freigabe_noetig: bool
    begruendung: str
    nummer: str | None = None
    fehler: str | None = None


def buche(con: sqlite3.Connection, *, nummer: str, betrag_eur: float, akteur: str,
          beleg: str, freigegeben_von: str | None = None,
          bezug: Vorgangsbezug = OHNE_BEZUG) -> Buchungsergebnis:
    """Verbucht eine Zahlung -- nach Policy-Pruefung.

    `freigegeben_von` wird gesetzt, wenn ein Mensch den HITL-Punkt bereits
    entschieden hat. Dann entfaellt die erneute Policy-Freigabepruefung: die
    Freigabe *ist* die Erlaubnis, sonst liefe der Vorgang in eine Endlosschleife
    aus Freigabe und erneuter Nachfrage.
    """
    if freigegeben_von is None:
        entscheid = pruefe_schreibaktion(
            con, agent_id=AGENT_ID, akteur=akteur, aktion="zahlung_verbuchen",
            betrag_eur=betrag_eur,
        )

        if entscheid.ergebnis is Ergebnis.VERWEIGERT:
            protokolliere(con, akteur=akteur, agent=AGENT_ID, aktion="zahlung_verbuchen",
                          entscheidung=Entscheidung.VERWEIGERT,
                          begruendung=entscheid.begruendung,
                          payload={"nummer": nummer, "regel": entscheid.regel},
                          bezug=bezug, ergebnis="verweigert")
            con.commit()
            return Buchungsergebnis(False, False, entscheid.begruendung, nummer)

        if entscheid.braucht_freigabe:
            protokolliere(con, akteur=akteur, agent=AGENT_ID, aktion="freigabe_angefordert",
                          entscheidung=Entscheidung.INFO, begruendung=entscheid.begruendung,
                          payload={"nummer": nummer, "betrag_eur": betrag_eur,
                                   "regel": entscheid.regel},
                          bezug=bezug, ergebnis="freigabe_noetig")
            con.commit()
            return Buchungsergebnis(False, True, entscheid.begruendung, nummer)
    else:
        protokolliere(con, akteur=freigegeben_von, agent=AGENT_ID,
                      aktion="freigabe_erteilt", entscheidung=Entscheidung.ERLAUBT,
                      begruendung=f"Buchung von {freigegeben_von} freigegeben "
                                  "(Vier-Augen-Prinzip).",
                      payload={"nummer": nummer, "betrag_eur": betrag_eur,
                               "einspeiser": akteur},
                      bezug=bezug, ergebnis="freigegeben")
        con.commit()

    # Der ERP-Aufruf. Das Zielsystem prueft seine Vorbedingungen selbst -- ein
    # 409 hier ist ein fachlicher Befund (Dublette), kein Transportfehler.
    try:
        antwort = httpx.post(
            f"{einstellungen.navision_url}/booking",
            json={"nummer": nummer, "betrag_eur": betrag_eur, "akteur": akteur,
                  "beleg": beleg, "vorgang_id": bezug.vorgang_id},
            timeout=30.0,
        )
    except httpx.HTTPError as e:
        return Buchungsergebnis(
            False, False, f"Navision nicht erreichbar: {e}", nummer, fehler=str(e)
        )

    if antwort.status_code != 200:
        grund = antwort.json().get("detail", antwort.text)
        return Buchungsergebnis(False, False, f"Navision hat abgelehnt: {grund}",
                                nummer, fehler=grund)

    return Buchungsergebnis(
        True, False, f"Zahlung zu {nummer} verbucht, Status offen -> bezahlt.", nummer
    )
