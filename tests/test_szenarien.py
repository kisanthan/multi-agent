"""End-to-End-Tests der fuenf Demonstrationsszenarien.

Diese Tests fahren den vollstaendigen Graphen -- Reader, Klassifikation,
Orchestrator-Routing, Agenten, HITL-Interrupts, Zielsysteme, Audit. Nur zwei
Dinge sind ersetzt:

1. Das Sprachmodell (llm.extraktion.extrahiere) -- durch feste Extraktions-
   ergebnisse. So laufen die Tests ohne Ollama und deterministisch; geprueft
   wird die *Architektur*, nicht die Extraktionsguete des Modells.
2. Der HTTP-Transport zu den Mocks -- die FastAPI-Apps laufen per ASGI im
   selben Prozess, ohne echten Server.

Damit ist die gesamte Kette pruefbar, inklusive der HITL-Fortsetzung ueber den
Checkpoint. Das ist der Nachweis, dass die fuenf Szenarien der Arbeit tatsaech-
lich durchlaufen.
"""

from __future__ import annotations

import sqlite3
import uuid
from pathlib import Path

import pytest

from agents.schemas import Dokumenttyp, Klassifikation
from config import EINGANG_DIR, MANIFEST_PFAD
from governance.audit import verify_chain
from llm.extraktion import Extraktionsergebnis

PROJEKT_WURZEL = Path(__file__).parent.parent


# --------------------------------------------------------------- Fixtures

@pytest.fixture(scope="module", autouse=True)
def testdaten():
    """Setzt die synthetischen Daten voraus (Generierung ausserhalb).

    Bewusst NICHT hier generiert: der Faker-Import ist auf diesem Rechner sehr
    teuer (volle Platte). Die Daten werden einmal per `python -m data.generate`
    erzeugt; die Szenario-Tests arbeiten dagegen. Der Graph laeuft gegen die
    echte DB (nicht In-Memory), weil mehrere Verbindungen und die Mock-Services
    darauf zugreifen.
    """
    if not MANIFEST_PFAD.is_file() or not any(EINGANG_DIR.glob("*.pdf")):
        pytest.skip("Testdaten fehlen -- zuerst `python -m data.generate` ausfuehren.")
    yield


@pytest.fixture
def thread():
    return {"configurable": {"thread_id": f"test-{uuid.uuid4().hex[:8]}"}}


@pytest.fixture
def app(monkeypatch):
    """Kompilierter Graph mit gemocktem LLM und In-Prozess-Mocks."""
    from config import CHECKPOINT_PFAD
    Path(CHECKPOINT_PFAD).unlink(missing_ok=True)

    # --- Zielsysteme per ASGI in den Prozess holen ---
    # FastAPIs TestClient spricht die ASGI-App synchron an (httpx' ASGITransport
    # ist async-only und passt nicht zu den synchronen httpx.post-Aufrufen der
    # Agenten). So laufen die Mocks ohne echten Server im selben Prozess.
    from fastapi.testclient import TestClient

    from mocks import elo as elo_mock
    from mocks import navision as navision_mock

    navision_client = TestClient(navision_mock.app)
    elo_client = TestClient(elo_mock.app)

    # Die Agenten rufen bekannte Endpunkt-Pfade -- direkt auf die In-Prozess-
    # Mocks abbilden, statt einen echten Server zu starten.
    def fake_post(url, **kwargs):
        if url.endswith("/booking"):
            return navision_client.post("/booking", **kwargs)
        if url.endswith("/archive"):
            return elo_client.post("/archive", **kwargs)
        raise AssertionError(f"Unerwarteter POST an {url}")

    monkeypatch.setattr("agents.buchung.httpx.post", fake_post)
    monkeypatch.setattr("agents.zielsysteme.httpx.post", fake_post)

    from graph.workflow import kompiliere
    graph, cp_con = kompiliere()
    yield graph
    cp_con.close()
    navision_client.close()
    elo_client.close()


def _mock_klassifikation(monkeypatch, **felder):
    """Ersetzt den Extraktionsagenten durch ein festes Klassifikationsergebnis."""
    daten = Klassifikation(**felder)
    erg = Extraktionsergebnis(daten=daten, versuche=1, modell="mock", anbieter="mock")
    monkeypatch.setattr("agents.klassifikation.extrahiere", lambda *a, **k: erg)


def _reset_status(nummer: str, status: str = "offen") -> None:
    from config import DB_PFAD
    con = sqlite3.connect(DB_PFAD)
    con.execute("UPDATE rechnungen SET status = ?, bezahlt_am = NULL WHERE nummer = ?",
                (status, nummer))
    con.commit()
    con.close()


def _pdf(name: str) -> str:
    return str(EINGANG_DIR / name)


# ------------------------------------------------- Szenario 1: Happy Path A

def test_szenario1_gueltige_zahlung_braucht_buchungsfreigabe(app, thread, monkeypatch):
    """Gueltige Zahlung -> Abgleich ok -> Buchungsfreigabe (HITL) -> offen->bezahlt.

    Thesis §7.4: der finanzwirksame Buchungsschritt steht unter Human-in-the-loop.
    Auch bei gueltiger, eindeutiger Zuordnung wird die Buchung erst nach einer
    menschlichen Freigabe ausgefuehrt -- es gibt keine automatische Verbuchung.
    """
    _reset_status("RE-2026-4200")
    _set_betrag("RE-2026-4200", 1_500.0)
    _mock_klassifikation(
        monkeypatch, typ=Dokumenttyp.ZAHLUNGSBESTAETIGUNG,
        nummer="RE-2026-4200", betrag_eur=1_500.0,
        lieferant="Microsoft Deutschland GmbH",
    )

    from langgraph.types import Command
    zustand = app.invoke(
        {"pfad": _pdf("A_zahlung_ok_01.pdf"), "akteur": "m.keller@chg-meridian.com",
         "protokoll": []},
        thread,
    )

    # Buchung ist immer HITL -> auch der Happy Path haelt fuer die Freigabe an.
    assert "__interrupt__" in zustand
    assert zustand["__interrupt__"][0].value["befund"] == "ok"

    zustand = app.invoke(
        Command(resume={"entscheidung": "freigegeben",
                        "pruefer": "s.hofmann@chg-meridian.com",
                        "nummer": "RE-2026-4200"}),
        thread,
    )
    assert zustand["ergebnis"] == "verbucht"

    from config import DB_PFAD
    con = sqlite3.connect(DB_PFAD)
    status = con.execute("SELECT status FROM rechnungen WHERE nummer = ?",
                         ("RE-2026-4200",)).fetchone()[0]
    assert verify_chain(con).gueltig
    con.close()
    assert status == "bezahlt"


def test_szenario1_grosser_betrag_gleiche_einzelfreigabe(app, thread, monkeypatch):
    """Auch ein hoher Betrag laeuft ueber genau eine Freigabe -- keine Schwelle.

    Belegt, dass es keinen betragsabhaengigen Sonderpfad gibt: 500.000 EUR
    durchlaufen dieselbe einzelne Human-in-the-loop-Freigabe wie 1.500 EUR.
    """
    _reset_status("RE-2026-4200")
    _set_betrag("RE-2026-4200", 500_000.0)
    _mock_klassifikation(
        monkeypatch, typ=Dokumenttyp.ZAHLUNGSBESTAETIGUNG,
        nummer="RE-2026-4200", betrag_eur=500_000.0,
    )

    from langgraph.types import Command
    zustand = app.invoke(
        {"pfad": _pdf("A_zahlung_ok_01.pdf"), "akteur": "m.keller@chg-meridian.com",
         "protokoll": []},
        thread,
    )
    assert "__interrupt__" in zustand

    zustand = app.invoke(
        Command(resume={"entscheidung": "freigegeben",
                        "pruefer": "s.hofmann@chg-meridian.com",
                        "nummer": "RE-2026-4200"}),
        thread,
    )
    assert zustand["ergebnis"] == "verbucht"


def _set_betrag(nummer: str, betrag: float) -> None:
    from config import DB_PFAD
    con = sqlite3.connect(DB_PFAD)
    con.execute("UPDATE rechnungen SET betrag_eur = ? WHERE nummer = ?", (betrag, nummer))
    con.commit()
    con.close()


# ---------------------------------------- Szenario 2: unbekannte Nummer

def test_szenario2_unbekannte_nummer_wird_zum_klaerfall(app, thread, monkeypatch):
    """Unbekannte Nummer -> Klaerfall -> Pruefer korrigiert -> Verbuchung."""
    _reset_status("RE-2026-4201")
    _set_betrag("RE-2026-4201", 2_000.0)
    _mock_klassifikation(
        monkeypatch, typ=Dokumenttyp.ZAHLUNGSBESTAETIGUNG,
        nummer="RE-2026-9999", betrag_eur=2_000.0,
    )

    from langgraph.types import Command
    zustand = app.invoke(
        {"pfad": _pdf("A_zahlung_unbekannte_nummer.pdf"),
         "akteur": "m.keller@chg-meridian.com", "protokoll": []},
        thread,
    )

    assert "__interrupt__" in zustand
    anfrage = zustand["__interrupt__"][0].value
    assert anfrage["befund"] == "unbekannt"

    # Pruefer korrigiert auf eine existierende, offene Nummer.
    zustand = app.invoke(
        Command(resume={"entscheidung": "freigegeben",
                        "pruefer": "s.hofmann@chg-meridian.com",
                        "nummer": "RE-2026-4201"}),
        thread,
    )
    assert zustand["ergebnis"] == "verbucht"


def test_szenario2_verwerfen_bucht_nicht(app, thread, monkeypatch):
    """Der Pruefer kann den Klaerfall auch verwerfen -- dann keine Buchung."""
    _mock_klassifikation(
        monkeypatch, typ=Dokumenttyp.ZAHLUNGSBESTAETIGUNG,
        nummer="RE-2026-9999", betrag_eur=None,
    )
    from langgraph.types import Command
    zustand = app.invoke(
        {"pfad": _pdf("A_zahlung_unbekannte_nummer.pdf"),
         "akteur": "m.keller@chg-meridian.com", "protokoll": []},
        thread,
    )
    zustand = app.invoke(
        Command(resume={"entscheidung": "verworfen",
                        "pruefer": "s.hofmann@chg-meridian.com"}),
        thread,
    )
    assert zustand["ergebnis"] == "verworfen"


# ------------------------------------------- Szenario 3: Happy Path B

def test_szenario3_eindeutige_kostenstelle_wird_automatisch_archiviert(app, thread, monkeypatch):
    """Rechnung -> eindeutige Kostenstelle -> automatische Archivierung in ELO.

    Neuer Prozess B (Diagramm Teil 3): der Kostenstellen-Agent ist
    Human-on-the-loop. Bei eindeutiger Zuordnung laeuft der Vorgang OHNE Freigabe
    durch bis zur revisionssicheren Ablage -- ELO ist das Prozessende, es gibt
    keine Navision-Verbuchung mehr in Prozess B.
    """
    _mock_klassifikation(
        monkeypatch, typ=Dokumenttyp.EINGANGSRECHNUNG,
        nummer="ER-2026-7102", betrag_eur=37_940.0,
        lieferant="Microsoft Deutschland GmbH",
        positionen=["Microsoft 365 E5, 1200 Lizenzen", "Azure Cloud Hosting"],
        kostenstellen_referenz="KTR-ITINFRA",  # loest eindeutig auf KST-1000
    )

    zustand = app.invoke(
        {"pfad": _pdf("B_rechnung_ok_02.pdf"), "akteur": "m.keller@chg-meridian.com",
         "protokoll": []},
        thread,
    )

    # Referenz loest eindeutig auf -> Human-on-the-loop -> kein Interrupt.
    assert "__interrupt__" not in zustand
    assert zustand["ergebnis"] == "archiviert"
    assert zustand["kostenstelle_id"] == "KST-1000"
    assert zustand["archiv_id"].startswith("ELO-")

    from config import DB_PFAD
    con = sqlite3.connect(DB_PFAD)
    row = con.execute("SELECT archiv_id FROM archiv WHERE archiv_id = ?",
                      (zustand["archiv_id"],)).fetchone()
    assert row is not None  # revisionssicher abgelegt
    assert verify_chain(con).gueltig
    con.close()


# ---------------------------------------- Szenario 4: Referenz fehlt

def test_szenario4_fehlende_referenz_entscheidet_mensch(app, thread, monkeypatch):
    """Keine Belegreferenz -> Nachschlag scheitert -> Klaerfall -> Mensch waehlt.

    Der exakte Nachschlag ist nicht eindeutig, sobald die Referenz fehlt. Dann
    greift die Vier-Augen-Freigabe; die menschliche Wahl bestimmt die
    Kostenstelle und ist im Audit-Trail nachvollziehbar.
    """
    _mock_klassifikation(
        monkeypatch, typ=Dokumenttyp.EINGANGSRECHNUNG,
        nummer="ER-2026-7200", betrag_eur=24_400.0,
        lieferant="SAP Deutschland SE",
        positionen=["SAP Lizenzverlaengerung Modul FI", "Anwenderschulung SAP FI"],
        kostenstellen_referenz=None,  # keine Referenz auf dem Beleg
    )

    from langgraph.types import Command
    zustand = app.invoke(
        {"pfad": _pdf("B_rechnung_ohne_referenz.pdf"),
         "akteur": "t.brandt@chg-meridian.com", "protokoll": []},
        thread,
    )

    assert "__interrupt__" in zustand
    anfrage = zustand["__interrupt__"][0].value
    assert anfrage["eindeutig"] is False
    # Der Pruefer bekommt den vollstaendigen Katalog zur Auswahl.
    assert any(k["id"] == "KST-5000" for k in anfrage["katalog"])

    # Mensch entscheidet sich fuer HR-Schulung.
    zustand = app.invoke(
        Command(resume={"entscheidung": "freigegeben",
                        "pruefer": "s.hofmann@chg-meridian.com",
                        "kostenstelle_id": "KST-5000"}),
        thread,
    )
    assert zustand["ergebnis"] == "archiviert"
    assert zustand["archiv_id"].startswith("ELO-")
    assert zustand["kostenstelle_id"] == "KST-5000"  # menschliche Wahl im State

    from config import DB_PFAD

    from governance.audit import lies_alle
    con = sqlite3.connect(DB_PFAD)
    # Die menschliche Wahl ist im Audit-Trail nachvollziehbar.
    freigaben = [e for e in lies_alle(con)
                 if e.aktion == "kostenstelle_freigegeben"]
    assert any("KST-5000" in e.begruendung for e in freigaben)
    assert verify_chain(con).gueltig
    con.close()


# ---------------------------------------- Szenario 5: ohne Modell

def test_szenario5_unberechtigter_einspeiser(app, thread):
    """AD-Check verweigert -> kein Modell, kein Ziel, ein Audit-Eintrag."""
    zustand = app.invoke(
        {"pfad": _pdf("A_zahlung_unberechtigt.pdf"),
         "akteur": "e.extern@partner-consulting.de", "protokoll": []},
        thread,
    )
    assert zustand["ergebnis"] == "zugriff_verweigert"
    assert "__interrupt__" not in zustand
    # Genau ein Schritt: der Reader-Knoten, sonst nichts.
    assert [s["knoten"] for s in zustand["protokoll"]] == ["reader"]
