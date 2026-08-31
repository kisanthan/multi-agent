"""Identity boundary for the UI.

The prototype implementation reads the synthetic directory from SQLite.
Production authentication can replace this provider with an OIDC/Entra
implementation without making page routing or sidebar rendering depend on
directory SQL.
"""

from __future__ import annotations

import sqlite3
from dataclasses import dataclass
from pathlib import Path
from typing import Protocol

from governance.ad import ensure_configuration_seed
from ui.shared.user import User, load


@dataclass(frozen=True)
class Account:
    upn: str
    display_name: str


class IdentityProvider(Protocol):
    """Small surface the UI needs from an identity system."""

    def accounts(self) -> list[Account]: ...

    def user(self, upn: str) -> User: ...


class SqliteIdentityProvider:
    """Prototype directory adapter backed by the generated SQLite data."""

    def __init__(self, database: Path | str):
        self._database = database

    def accounts(self) -> list[Account]:
        con = sqlite3.connect(self._database)
        try:
            ensure_configuration_seed(con)
            return [Account(*row) for row in con.execute(
                "SELECT upn, display_name FROM ad_users ORDER BY display_name"
            ).fetchall()]
        finally:
            con.close()

    def user(self, upn: str) -> User:
        con = sqlite3.connect(self._database)
        try:
            return load(con, upn)
        finally:
            con.close()
