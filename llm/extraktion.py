"""Validierte, strukturierte Extraktion mit Retry und HITL-Eskalation.

Dieses Modul ist die Antwort auf Risiko R1 (docs/grenzen.md): lokale Modelle
halten ein uebergebenes JSON-Schema nicht zuverlaessig ein -- fuer Ollama ist
das ein offener, dokumentierter Bug (ollama/ollama#15540, Stand April 2026).

Die Gegenmassnahme ist aber kein Workaround, sondern selbst eine Aussage der
Arbeit: die Unzuverlaessigkeit des Modells wird von einer deterministischen
Schicht *abgefangen* statt vom Modell *versprochen*. Scheitert die Validierung
auch nach dem Retry, wird nicht geraten und nicht mit halben Daten
weitergearbeitet -- der Fall geht an den Menschen. Damit ist ein Modellfehler
ein Freigabefall und kein stiller Datenfehler.

Kein Vertrauensvorschuss an das Modell: auch die Cloud-Antwort laeuft durch
dieselbe Validierung.
"""

from __future__ import annotations

import json
import sqlite3
from dataclasses import dataclass

from pydantic import BaseModel, ValidationError

from governance.audit import Entscheidung, protokolliere
from llm.client import LLMNichtErreichbar, client_fuer

MAX_VERSUCHE = 2


@dataclass(frozen=True)
class Extraktionsergebnis:
    """Ergebnis eines Extraktionsversuchs.

    `daten is None` und `eskalation is not None` sind aequivalent und bedeuten:
    Klaerfall. Der Aufrufer darf nie auf ein Feld zugreifen, ohne vorher
    `gelungen` geprueft zu haben.
    """

    daten: BaseModel | None
    versuche: int
    modell: str
    anbieter: str
    eskalation: str | None = None
    roh: str = ""

    @property
    def gelungen(self) -> bool:
        return self.daten is not None


def _fehlertext(e: ValidationError) -> str:
    """Uebersetzt Pydantic-Fehler in eine Korrekturanweisung fuers Modell."""
    zeilen = []
    for f in e.errors():
        pfad = ".".join(str(t) for t in f["loc"]) or "(Wurzel)"
        zeilen.append(f"- Feld {pfad}: {f['msg']}")
    return "\n".join(zeilen)


def extrahiere(
    con: sqlite3.Connection,
    *,
    agent_id: str,
    akteur: str,
    system: str,
    prompt: str,
    schema: type[BaseModel],
) -> Extraktionsergebnis:
    """Ruft das Modell und validiert die Antwort gegen `schema`.

    Bei Schemaverletzung genau ein Nachfassversuch mit dem konkreten
    Validierungsfehler. Danach Eskalation -- kein dritter Versuch, weil ein
    Modell, das zweimal am selben Schema scheitert, das Schema nicht versteht
    und ein weiterer Durchlauf nur Kosten und Latenz erzeugt.
    """
    client, wahl = client_fuer(agent_id)
    aktueller_prompt = prompt
    letzter_fehler = ""
    roh = ""

    for versuch in range(1, MAX_VERSUCHE + 1):
        try:
            roh = client.frage_json(system=system, prompt=aktueller_prompt, schema=schema)
        except LLMNichtErreichbar as e:
            # Transportfehler: nicht wiederholen, sondern sichtbar machen.
            protokolliere(
                con, akteur=akteur, agent=agent_id, aktion="llm_aufruf",
                entscheidung=Entscheidung.VERWEIGERT,
                begruendung=f"Modell nicht erreichbar: {e}",
                payload={"modell": wahl.modell_id, "anbieter": wahl.anbieter},
            )
            con.commit()
            return Extraktionsergebnis(
                None, versuch, wahl.modell_id, wahl.anbieter,
                eskalation=f"Modell nicht erreichbar: {e}",
            )

        try:
            daten = schema.model_validate_json(roh)
        except ValidationError as e:
            letzter_fehler = _fehlertext(e)
            protokolliere(
                con, akteur=akteur, agent=agent_id, aktion="llm_schemaverletzung",
                entscheidung=Entscheidung.INFO,
                begruendung=f"Versuch {versuch}/{MAX_VERSUCHE} verletzt das Schema.",
                payload={"modell": wahl.modell_id, "anbieter": wahl.anbieter,
                         "fehler": letzter_fehler},
            )
            con.commit()
            aktueller_prompt = (
                f"{prompt}\n\n"
                f"Dein vorheriger Versuch war ungueltig:\n{roh}\n\n"
                f"Diese Felder waren falsch:\n{letzter_fehler}\n\n"
                "Antworte erneut, ausschliesslich mit gueltigem JSON nach dem Schema."
            )
            continue

        protokolliere(
            con, akteur=akteur, agent=agent_id, aktion="llm_extraktion",
            entscheidung=Entscheidung.INFO,
            begruendung=f"Extraktion gelungen in Versuch {versuch}.",
            payload={"modell": wahl.modell_id, "anbieter": wahl.anbieter,
                     "ergebnis": json.loads(daten.model_dump_json())},
        )
        con.commit()
        return Extraktionsergebnis(daten, versuch, wahl.modell_id, wahl.anbieter, roh=roh)

    # Beide Versuche gescheitert -> Klaerfall statt Raten.
    eskalation = (
        f"Das Modell {wahl.modell_id} hat das Schema in {MAX_VERSUCHE} Versuchen "
        f"nicht eingehalten. Letzte Fehler:\n{letzter_fehler}"
    )
    protokolliere(
        con, akteur=akteur, agent=agent_id, aktion="llm_eskalation",
        entscheidung=Entscheidung.VERWEIGERT, begruendung=eskalation,
        payload={"modell": wahl.modell_id, "anbieter": wahl.anbieter, "roh": roh[:2000]},
    )
    con.commit()
    return Extraktionsergebnis(
        None, MAX_VERSUCHE, wahl.modell_id, wahl.anbieter,
        eskalation=eskalation, roh=roh,
    )
