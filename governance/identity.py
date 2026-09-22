"""Local authenticated prototype identities; the directory is not authentication.

Only this trusted boundary handles passwords/session tokens. Secrets never enter
the graph or audit. An enterprise identity provider is a separate integration.
"""
from contextlib import contextmanager
from contextvars import ContextVar
import hashlib
import hmac
import secrets
import sqlite3
import time

from governance import ad

_session: ContextVar[str | None] = ContextVar("authenticated_session", default=None)


class AuthenticationError(PermissionError):
    pass


def digest(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()


def set_password(con: sqlite3.Connection, upn: str, password: str) -> None:
    """Trusted local provisioning operation, also used by test fixtures."""
    ad.load_user(con, upn)
    if len(password) < 12:
        raise ValueError("Das Passwort muss mindestens 12 Zeichen enthalten.")
    salt = secrets.token_hex(16)
    key = hashlib.scrypt(password.encode(), salt=bytes.fromhex(salt), n=16384, r=8, p=1)
    con.execute(
        "INSERT INTO local_credentials(upn,salt,password_hash) VALUES(?,?,?) "
        "ON CONFLICT(upn) DO UPDATE SET salt=excluded.salt,password_hash=excluded.password_hash,"
        "active=1,failures=0,locked_until=0", (upn, salt, key.hex()))
    con.execute("DELETE FROM auth_sessions WHERE upn=?", (upn,))
    con.commit()


def ensure_portal_identities(con: sqlite3.Connection) -> None:
    """Install the documented admin and internal demo-session prerequisites.

    Existing credentials are never reset. This keeps an explicitly changed
    administrator password stable across application restarts.
    """
    from config import settings

    ad.ensure_additional_demo_users(con)

    con.execute(
        "INSERT OR IGNORE INTO ad_users(upn,display_name,role) VALUES(?,?,?)",
        (settings.portal_admin_email, "Prototype Administrator", ad.Role.APPROVER.value),
    )
    for group, description in (
        (ad.READER_GROUP, "Darf Belege einspeisen"),
        (ad.APPROVAL_GROUP, "Darf kontrollierte Freigaben erteilen"),
        (ad.CONFIGURATION_GROUP, "Darf Agenten- und Systemeinstellungen ändern"),
    ):
        con.execute("INSERT OR IGNORE INTO ad_groups(name,description) VALUES(?,?)",
                    (group, description))
        con.execute("INSERT OR IGNORE INTO ad_memberships(upn,group_name) VALUES(?,?)",
                    (settings.portal_admin_email, group))
    con.commit()
    if not con.execute("SELECT 1 FROM local_credentials WHERE upn=?",
                       (settings.portal_admin_email,)).fetchone():
        set_password(con, settings.portal_admin_email, settings.portal_admin_password)

    if settings.portal_mode.value == "demo":
        # Demo sessions use unknown random passwords internally. They can only
        # be issued while PORTAL_MODE=demo and therefore do not create a
        # second documented password login path.
        for upn in demo_portal_upns():
            ad.load_user(con, upn)
            if not con.execute("SELECT 1 FROM local_credentials WHERE upn=?", (upn,)).fetchone():
                set_password(con, upn, secrets.token_urlsafe(32))


def demo_portal_upns() -> tuple[str, ...]:
    """Identities offered by the passwordless local demo portal."""
    from config import settings

    return tuple(dict.fromkeys((
        settings.demo_submitter_upn,
        settings.demo_approver_upn,
        *ad.additional_demo_upns(),
    )))


def issue_demo_session(con: sqlite3.Connection, upn: str) -> str:
    """Issue a passwordless session for a seeded synthetic demo identity.

    The Streamlit portal exposes only its configured submitter and approver.
    The CLI may additionally use the other synthetic seed identities so the
    unauthorized-access scenario remains demonstrable without introducing a
    real login flow.
    """
    from config import PortalMode, settings

    if settings.portal_mode is not PortalMode.DEMO:
        raise AuthenticationError("Passwortlose Demositzungen sind nur im Demo-Modus zulässig.")
    ensure_portal_identities(con)
    try:
        ad.load_user(con, upn)
    except ad.UnknownUser as error:
        raise AuthenticationError("Diese Identität ist keine synthetische Demo-Rolle.") from error
    if not con.execute("SELECT 1 FROM local_credentials WHERE upn=?", (upn,)).fetchone():
        set_password(con, upn, secrets.token_urlsafe(32))
    row = con.execute("SELECT active FROM local_credentials WHERE upn=?", (upn,)).fetchone()
    if not row or not row[0]:
        raise AuthenticationError("Die Demo-Identität ist deaktiviert.")
    token = secrets.token_urlsafe(32)
    con.execute("INSERT INTO auth_sessions VALUES(?,?,?)",
                (digest(token), upn, time.time() + 8 * 3600))
    con.commit()
    return token


def login(con: sqlite3.Connection, upn: str, password: str) -> str:
    row = con.execute("SELECT salt,password_hash,active,failures,locked_until "
                      "FROM local_credentials WHERE upn=?", (upn,)).fetchone()
    # Constant-cost dummy derivation also for unknown accounts.
    salt = row[0] if row else "00" * 16
    key = hashlib.scrypt(password.encode(), salt=bytes.fromhex(salt), n=16384, r=8, p=1)
    if not row or not row[2] or row[4] > time.time() or not hmac.compare_digest(key.hex(), row[1]):
        if row:
            count = row[3] + 1
            con.execute("UPDATE local_credentials SET failures=?,locked_until=? WHERE upn=?",
                        (count, time.time() + 300 if count >= 5 else 0, upn))
            con.commit()
        raise AuthenticationError("Anmeldung nicht möglich.")
    ad.load_user(con, upn)
    token = secrets.token_urlsafe(32)
    con.execute("UPDATE local_credentials SET failures=0,locked_until=0 WHERE upn=?", (upn,))
    con.execute("INSERT INTO auth_sessions VALUES(?,?,?)", (digest(token), upn, time.time() + 8 * 3600))
    con.commit()
    return token


def principal(con: sqlite3.Connection, token: str | None = None) -> str:
    value = token if token is not None else _session.get()
    if not value:
        raise AuthenticationError("Eine authentifizierte Sitzung ist erforderlich.")
    row = con.execute(
        "SELECT s.upn FROM auth_sessions s JOIN local_credentials c ON c.upn=s.upn "
        "WHERE s.token_hash=? AND s.expires>? AND c.active=1",
        (digest(value), time.time())).fetchone()
    if not row:
        raise AuthenticationError("Die Sitzung ist abgelaufen oder widerrufen.")
    ad.load_user(con, row[0])
    return row[0]


def logout(con: sqlite3.Connection, token: str) -> None:
    con.execute("DELETE FROM auth_sessions WHERE token_hash=?", (digest(token),))
    con.commit()


@contextmanager
def session(token: str):
    handle = _session.set(token)
    try:
        yield
    finally:
        _session.reset(handle)


def main():
    import argparse
    import getpass
    import config
    from data.bootstrap import ensure_configured_runtime
    from data.migrations import connect
    parser = argparse.ArgumentParser(description="Lokales Demokonto einrichten; keine Cloudidentität.")
    parser.add_argument("upn")
    args = parser.parse_args()
    ensure_configured_runtime()
    with connect(config.DB_PATH) as con:
        password = getpass.getpass("Neues Passwort (mindestens 12 Zeichen): ")
        if password != getpass.getpass("Passwort wiederholen: "):
            raise SystemExit("Passwörter stimmen nicht überein.")
        set_password(con, args.upn, password)
    print("Lokales Konto eingerichtet.")


if __name__ == "__main__":
    main()
