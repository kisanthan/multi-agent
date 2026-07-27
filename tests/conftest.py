from __future__ import annotations

import sqlite3
import sys
from pathlib import Path

import pytest

PROJEKT_WURZEL = Path(__file__).parent.parent
sys.path.insert(0, str(PROJEKT_WURZEL))


@pytest.fixture
def con() -> sqlite3.Connection:
    """Frische In-Memory-Datenbank mit dem Produktivschema und Minimal-AD.

    In-Memory statt einer Kopie der generierten DB: die Governance-Tests sollen
    gegen bekannte, kleine Fixtures pruefen und nicht gegen 50 Zufallsrechnungen.
    """
    con = sqlite3.connect(":memory:")
    con.executescript((PROJEKT_WURZEL / "data" / "schema.sql").read_text(encoding="utf-8"))

    con.executemany("INSERT INTO ad_gruppen VALUES (?,?)", [
        ("SG-CHG-DocIngest", "Darf einspeisen"),
        ("SG-CHG-Freigabe", "Darf freigeben"),
    ])
    con.executemany("INSERT INTO ad_nutzer VALUES (?,?,?)", [
        ("einspeiser@chg-meridian.com", "Erika Einspeiser", "einspeiser"),
        ("pruefer@chg-meridian.com", "Peter Pruefer", "pruefer"),
        ("extern@partner.de", "Erik Extern", "beobachter"),
    ])
    con.executemany("INSERT INTO ad_mitgliedschaften VALUES (?,?)", [
        ("einspeiser@chg-meridian.com", "SG-CHG-DocIngest"),
        ("pruefer@chg-meridian.com", "SG-CHG-DocIngest"),
        ("pruefer@chg-meridian.com", "SG-CHG-Freigabe"),
        # 'extern@partner.de' bewusst ohne jede Mitgliedschaft.
    ])
    con.commit()
    yield con
    con.close()
