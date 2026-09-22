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

# Additional identities exposed by the local demo portal.  They deliberately
# cover the two combinations requested for the walkthrough: one person may
# submit and approve, while the other may only submit.  The four-eyes check is
# independent of these group memberships and still prevents self-approval.
ADDITIONAL_DEMO_USERS = (
    (
        "l.schneider@chg-meridian.com",
        "Laura Schneider",
        "pruefer",
        frozenset({READER_GROUP, APPROVAL_GROUP}),
    ),
    (
        "j.becker@chg-meridian.com",
        "Jonas Becker",
        "einspeiser",
        frozenset({READER_GROUP}),
    ),
)


def additional_demo_upns() -> tuple[str, ...]:
    return tuple(user[0] for user in ADDITIONAL_DEMO_USERS)


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
    created = con.execute(
        "INSERT OR IGNORE INTO ad_groups (name, description) VALUES (?,?)",
        (CONFIGURATION_GROUP, "Darf Agenten- und Anbieter-Einstellungen ändern"),
    )
    exists = con.execute(
        "SELECT 1 FROM ad_users WHERE upn = 's.hofmann@chg-meridian.com'"
    ).fetchone()
    if exists and created.rowcount == 1:
        con.execute(
            "INSERT OR IGNORE INTO ad_memberships (upn, group_name) VALUES (?,?)",
            ("s.hofmann@chg-meridian.com", CONFIGURATION_GROUP),
        )
    con.commit()


def ensure_additional_demo_users(con: sqlite3.Connection) -> None:
    """Add the extended demo identities without replacing existing data."""
    for group, description in (
        (READER_GROUP, "Darf Dokumente in das Reader-Tool einspeisen"),
        (APPROVAL_GROUP, "Darf Klaerfaelle und Kostenstellen-Zuordnungen freigeben"),
    ):
        con.execute(
            "INSERT OR IGNORE INTO ad_groups(name,description) VALUES(?,?)",
            (group, description),
        )
    for upn, display_name, role, groups in ADDITIONAL_DEMO_USERS:
        con.execute(
            "INSERT OR IGNORE INTO ad_users(upn,display_name,role) VALUES(?,?,?)",
            (upn, display_name, role),
        )
        for group in groups:
            con.execute(
                "INSERT OR IGNORE INTO ad_memberships(upn,group_name) VALUES(?,?)",
                (upn, group),
            )
    con.commit()
