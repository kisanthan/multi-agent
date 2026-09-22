from __future__ import annotations

import sqlite3
import sys
import tempfile
from pathlib import Path

import pytest

PROJECT_ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

_RUNTIME_DIR: tempfile.TemporaryDirectory[str] | None = None


def pytest_configure(config) -> None:
    """Install one isolated runtime dataset before test modules are imported.

    The application deliberately opens short-lived connections from many
    modules. Redirecting the central paths before collection keeps those
    integration tests realistic without ever touching ``data/masterdata.db``
    or the developer's checkpoint and upload files. The same versioned seed
    bundle used by a fresh demo installation is the source.
    """
    global _RUNTIME_DIR

    import config as app_config

    _RUNTIME_DIR = tempfile.TemporaryDirectory(
        prefix="multi-agent-tests-", ignore_cleanup_errors=True
    )
    runtime = Path(_RUNTIME_DIR.name)
    app_config.DB_PATH = runtime / "masterdata.db"
    app_config.CHECKPOINT_PATH = runtime / "checkpoints.sqlite"
    app_config.INTAKE_DIR = runtime / "inbox"
    app_config.MANIFEST_PATH = runtime / "manifest.json"

    from data.bootstrap import ensure_configured_runtime

    ensure_configured_runtime()


def pytest_unconfigure(config) -> None:
    global _RUNTIME_DIR
    if _RUNTIME_DIR is not None:
        _RUNTIME_DIR.cleanup()
        _RUNTIME_DIR = None


@pytest.fixture
def con() -> sqlite3.Connection:
    """Fresh in-memory database with the production schema and minimal AD data.

    In-memory instead of a copy of the generated DB: the governance tests
    should check against known, small fixtures and not against 50 random
    invoices.
    """
    con = sqlite3.connect(":memory:")
    con.executescript((PROJECT_ROOT / "data" / "schema.sql").read_text(encoding="utf-8"))

    from data.migrations import migrate
    migrate(con)

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
