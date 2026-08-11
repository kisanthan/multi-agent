from __future__ import annotations

import sqlite3
import sys
from pathlib import Path

import pytest

PROJECT_ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(PROJECT_ROOT))


@pytest.fixture
def con() -> sqlite3.Connection:
    """Fresh in-memory database with the production schema and minimal AD data.

    In-memory instead of a copy of the generated DB: the governance tests
    should check against known, small fixtures and not against 50 random
    invoices.
    """
    con = sqlite3.connect(":memory:")
    con.executescript((PROJECT_ROOT / "data" / "schema.sql").read_text(encoding="utf-8"))

    con.executemany("INSERT INTO ad_groups VALUES (?,?)", [
        ("SG-CHG-DocIngest", "Darf einspeisen"),
        ("SG-CHG-Freigabe", "Darf freigeben"),
    ])
    con.executemany("INSERT INTO ad_users VALUES (?,?,?)", [
        ("einspeiser@chg-meridian.com", "Erika Einspeiser", "einspeiser"),
        ("pruefer@chg-meridian.com", "Peter Pruefer", "pruefer"),
        ("extern@partner.de", "Erik Extern", "beobachter"),
    ])
    con.executemany("INSERT INTO ad_memberships VALUES (?,?)", [
        ("einspeiser@chg-meridian.com", "SG-CHG-DocIngest"),
        ("pruefer@chg-meridian.com", "SG-CHG-DocIngest"),
        ("pruefer@chg-meridian.com", "SG-CHG-Freigabe"),
        # 'extern@partner.de' deliberately has no membership at all.
    ])
    con.commit()
    yield con
    con.close()
