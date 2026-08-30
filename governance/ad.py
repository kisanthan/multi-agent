"""AD/Entra mock: user, group, and role checks (Least Privilege).

Models the entry condition into the reader tool: only members of the AD
security group may submit documents (section 1 of the functional concept).
No LLM -- a permission check that a language model "decides" would not be a
permission check.
"""

from __future__ import annotations

import sqlite3
from dataclasses import dataclass
from enum import Enum

# The group whose membership the reader tool requires.
READER_GROUP = "SG-CHG-DocIngest"
# The group allowed to approve exception cases and cost-center assignments.
APPROVAL_GROUP = "SG-CHG-Freigabe"
# Dedicated right for changing provider credentials and global agent profiles.
CONFIGURATION_GROUP = "SG-CHG-Konfiguration"


class Role(str, Enum):
    SUBMITTER = "einspeiser"
    APPROVER = "pruefer"
    OBSERVER = "beobachter"


@dataclass(frozen=True)
class User:
    upn: str
    display_name: str
    role: Role
    groups: frozenset[str]

    def is_member(self, group: str) -> bool:
        return group in self.groups


class UnknownUser(Exception):
    """A UPN with no AD entry.

    Deliberately an exception instead of an anonymous default user: Zero
    Trust means an unknown actor does not silently pass through as
    minimally privileged, but aborts the case.
    """


def load_user(con: sqlite3.Connection, upn: str) -> User:
    row = con.execute(
        "SELECT upn, display_name, role FROM ad_users WHERE upn = ?", (upn,)
    ).fetchone()
    if row is None:
        raise UnknownUser(f"Kein AD-Eintrag fuer {upn!r}")

    groups = {
        g[0] for g in con.execute(
            "SELECT group_name FROM ad_memberships WHERE upn = ?", (upn,)
        ).fetchall()
    }
    return User(upn=row[0], display_name=row[1], role=Role(row[2]),
                groups=frozenset(groups))


@dataclass(frozen=True)
class AccessResult:
    allowed: bool
    reason: str
    user: User | None = None


def check_reader_access(con: sqlite3.Connection, upn: str) -> AccessResult:
    """Entry condition into the reader tool (scenario 5).

    Once this check is denied, *nothing* may happen afterwards: no parsing,
    no LLM call. That is exactly what tests/test_szenario5 verifies.
    """
    try:
        user = load_user(con, upn)
    except UnknownUser as e:
        return AccessResult(False, f"Zero Trust: {e}")

    if not user.is_member(READER_GROUP):
        return AccessResult(
            False,
            f"{user.display_name} ist nicht Mitglied der Sicherheitsgruppe "
            f"{READER_GROUP} (Least Privilege).",
            user,
        )
    return AccessResult(
        True, f"{user.display_name} ist Mitglied von {READER_GROUP}.", user
    )


def check_approval_permission(con: sqlite3.Connection, upn: str) -> AccessResult:
    """May this user decide a HITL approval point?

    Four-eyes principle: relevant for the cost-center approval (process B)
    and the exception-case/booking approval (process A).
    """
    try:
        user = load_user(con, upn)
    except UnknownUser as e:
        return AccessResult(False, f"Zero Trust: {e}")

    if not user.is_member(APPROVAL_GROUP):
        return AccessResult(
            False,
            f"{user.display_name} ist nicht Mitglied von {APPROVAL_GROUP} "
            "und darf keine Freigaben erteilen.",
            user,
        )
    return AccessResult(
        True, f"{user.display_name} ist freigabeberechtigt.", user
    )


def check_configuration_permission(con: sqlite3.Connection, upn: str) -> AccessResult:
    try:
        user = load_user(con, upn)
    except UnknownUser as e:
        return AccessResult(False, f"Zero Trust: {e}")
    if not user.is_member(CONFIGURATION_GROUP):
        return AccessResult(False, "Das Konto darf die Systemkonfiguration nicht ändern.", user)
    return AccessResult(True, f"{user.display_name} darf konfigurieren.", user)


def ensure_configuration_seed(con: sqlite3.Connection) -> None:
    """Non-destructive migration for databases generated before this feature."""
    con.execute(
        "INSERT OR IGNORE INTO ad_groups (name, description) VALUES (?,?)",
        (CONFIGURATION_GROUP, "Darf Agenten- und Anbieter-Einstellungen ändern"),
    )
    exists = con.execute(
        "SELECT 1 FROM ad_users WHERE upn = 's.hofmann@chg-meridian.com'"
    ).fetchone()
    if exists:
        con.execute(
            "INSERT OR IGNORE INTO ad_memberships (upn, group_name) VALUES (?,?)",
            ("s.hofmann@chg-meridian.com", CONFIGURATION_GROUP),
        )
    con.commit()
