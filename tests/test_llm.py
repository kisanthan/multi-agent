"""Tests der LLM-Abstraktion und der Validierungsschicht (Risiko R1).

Alle Tests laufen ohne echtes Modell: der Transport ist gemockt. Das ist
Absicht -- geprueft wird das *Verhalten bei* Modellantworten, nicht das Modell.
Genau diese Trennung macht die Architektur pruefbar.
"""

from __future__ import annotations

from contextlib import contextmanager
from unittest.mock import MagicMock, patch

import pytest
from pydantic import BaseModel, Field

from config import ModellModus, einstellungen
from governance.audit import lies_alle, verify_chain
from llm.client import LLMNichtErreichbar, Modellwahl, waehle_modell
from llm.extraktion import MAX_VERSUCHE, extrahiere

AKTEUR = "einspeiser@chg-meridian.com"


class Zahlung(BaseModel):
    nummer: str = Field(description="Rechnungs- oder Bestellnummer")
    betrag_eur: float


@contextmanager
def modell_antwortet(*antworten, modell: str = "qwen3:8b", anbieter: str = "ollama"):
    """Ersetzt den Transport durch feste Antworten.

    `client_fuer` liefert ein Tupel (Client, Modellwahl); der Mock muss daher
    ein echtes Tupel mit einer echten Modellwahl zurueckgeben -- ein MagicMock
    laesst sich nicht entpacken.

    Mehrere Argumente = aufeinanderfolgende Antworten. Eine Exception-Instanz
    wird geworfen statt zurueckgegeben.
    """
    client = MagicMock()
    if len(antworten) == 1 and not isinstance(antworten[0], BaseException):
        client.frage_json.return_value = antworten[0]
    else:
        client.frage_json.side_effect = list(antworten)

    wahl = Modellwahl(anbieter=anbieter, modell_id=modell, risikoklasse="test")
    with patch("llm.extraktion.client_fuer", return_value=(client, wahl)) as fabrik:
        yield client, fabrik


# ------------------------------------------------- Modellzuordnung (teil2)

def test_lokaler_modus_nutzt_ueberall_ollama():
    with patch.object(einstellungen, "modell_modus", ModellModus.LOKAL):
        for agent in ("orchestrator", "klassifikation", "buchung", "elo"):
            assert waehle_modell(agent).anbieter == "ollama"


def test_hybrid_modus_trennt_nach_risikoklasse():
    """Die Kernaussage von teil2_ki_modelle.png, im Code nachvollzogen."""
    with patch.object(einstellungen, "modell_modus", ModellModus.HYBRID):
        # Lesende/unkritische Rollen bleiben lokal -> Datenhoheit.
        assert waehle_modell("orchestrator").anbieter == "ollama"
        assert waehle_modell("elo").anbieter == "ollama"
        # Risikobehaftete Rollen bekommen ein Frontier-Modell.
        assert waehle_modell("buchung").anbieter == "anthropic"
        assert waehle_modell("klassifikation").anbieter == "anthropic"


def test_cloud_modus_nutzt_ueberall_anthropic():
    with patch.object(einstellungen, "modell_modus", ModellModus.CLOUD):
        assert waehle_modell("klassifikation").anbieter == "anthropic"
        assert waehle_modell("buchung").anbieter == "anthropic"


def test_frontier_agent_bekommt_frontier_modell():
    with patch.object(einstellungen, "modell_modus", ModellModus.HYBRID):
        assert waehle_modell("buchung").modell_id == einstellungen.cloud_modell_frontier


@pytest.mark.parametrize("agent_id", ["reader", "policy", "audit", "abgleich", "kostenstelle"])
def test_deterministische_komponenten_bekommen_kein_modell(agent_id):
    """Reader/Policy/Audit UND die deterministisch arbeitenden Domain-Agenten
    (Abgleich, Kostenstelle -- exakter Nachschlag) rufen kein Sprachmodell auf."""
    with pytest.raises(ValueError, match="kein Sprachmodell"):
        waehle_modell(agent_id)


# ------------------------------------- Validierung / Retry / Eskalation (R1)

def test_gueltige_antwort_im_ersten_versuch(con):
    with modell_antwortet('{"nummer": "RE-2026-4200", "betrag_eur": 1341.96}'):
        e = extrahiere(con, agent_id="klassifikation", akteur=AKTEUR,
                       system="s", prompt="p", schema=Zahlung)

    assert e.gelungen
    assert e.versuche == 1
    assert e.daten.nummer == "RE-2026-4200"
    assert e.daten.betrag_eur == 1341.96
    assert e.eskalation is None


def test_schemaverletzung_wird_einmal_nachgefasst(con):
    """R1: erst korrigieren lassen, dann erst eskalieren."""
    with modell_antwortet(
        '{"nummer": "RE-2026-4200"}',                        # betrag_eur fehlt
        '{"nummer": "RE-2026-4200", "betrag_eur": 1341.96}',  # Korrektur
    ) as (client, _):
        e = extrahiere(con, agent_id="klassifikation", akteur=AKTEUR,
                       system="s", prompt="p", schema=Zahlung)

    assert e.gelungen
    assert e.versuche == 2
    assert client.frage_json.call_count == 2


def test_nachfassen_nennt_den_konkreten_fehler(con):
    """Der Retry-Prompt muss das fehlende Feld benennen, sonst rate das Modell nur."""
    with modell_antwortet(
        '{"nummer": "RE-2026-4200"}',
        '{"nummer": "RE-2026-4200", "betrag_eur": 1341.96}',
    ) as (client, _):
        extrahiere(con, agent_id="klassifikation", akteur=AKTEUR,
                   system="s", prompt="p", schema=Zahlung)

    zweiter_prompt = client.frage_json.call_args_list[1].kwargs["prompt"]
    assert "betrag_eur" in zweiter_prompt


def test_dauerhafte_schemaverletzung_eskaliert_statt_zu_raten(con):
    """Der entscheidende Test fuer R1.

    Scheitert das Modell zweimal, wird kein Teilergebnis geliefert und nichts
    geraten -- der Fall geht an den Menschen. Ein Modellfehler wird damit zum
    Freigabefall, nicht zum stillen Datenfehler.
    """
    with modell_antwortet('{"quatsch": true}', modell="gemma4:26b") as (client, _):
        e = extrahiere(con, agent_id="klassifikation", akteur=AKTEUR,
                       system="s", prompt="p", schema=Zahlung)

    assert not e.gelungen
    assert e.daten is None
    assert e.eskalation is not None
    assert e.versuche == MAX_VERSUCHE
    assert client.frage_json.call_count == MAX_VERSUCHE  # kein dritter Versuch


def test_kein_json_eskaliert(con):
    """Ollama liefert laut #15540 gelegentlich Prosa statt JSON."""
    with modell_antwortet("Klar! Die Nummer lautet RE-2026-4200."):
        e = extrahiere(con, agent_id="klassifikation", akteur=AKTEUR,
                       system="s", prompt="p", schema=Zahlung)

    assert not e.gelungen


def test_nicht_erreichbares_modell_wird_nicht_wiederholt(con):
    """Transportfehler ist ein Betriebsproblem -- Retry hilft da nicht."""
    with modell_antwortet(LLMNichtErreichbar("ollama serve laeuft nicht")) as (client, _):
        e = extrahiere(con, agent_id="klassifikation", akteur=AKTEUR,
                       system="s", prompt="p", schema=Zahlung)

    assert not e.gelungen
    assert "nicht erreichbar" in e.eskalation
    assert client.frage_json.call_count == 1


# ------------------------------------------------------ Audit-Kopplung

def test_eskalation_ist_im_audit_nachvollziehbar(con):
    """Auch ein Modellversagen muss im Trail stehen -- sonst fehlt es der Revision."""
    with modell_antwortet('{"quatsch": true}', modell="gemma4:26b"):
        extrahiere(con, agent_id="klassifikation", akteur=AKTEUR,
                   system="s", prompt="p", schema=Zahlung)

    aktionen = [e.aktion for e in lies_alle(con)]
    assert aktionen.count("llm_schemaverletzung") == MAX_VERSUCHE
    assert "llm_eskalation" in aktionen
    assert verify_chain(con).gueltig


def test_erfolgreiche_extraktion_protokolliert_das_modell(con):
    """Nachvollziehbarkeit: welches Modell hat welches Ergebnis geliefert?"""
    with modell_antwortet('{"nummer": "RE-2026-4200", "betrag_eur": 1341.96}'):
        extrahiere(con, agent_id="klassifikation", akteur=AKTEUR,
                   system="s", prompt="p", schema=Zahlung)

    eintrag = lies_alle(con)[-1]
    assert eintrag.aktion == "llm_extraktion"
    assert eintrag.agent == "klassifikation"
    assert verify_chain(con).gueltig
