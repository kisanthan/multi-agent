"""What the signed-in human may do -- in words they understand.

The governance layer answers precisely and technically: "X is not a member
of security group SG-CHG-Freigabe (Least Privilege)". That is exactly right
as an audit entry and useless as on-screen text.

This module is the translation layer between the two. It decides nothing --
the rules stay in `governance/` -- it only phrases what they mean, and
which hints make sense on which page at all.
"""

from __future__ import annotations

import sqlite3
from dataclasses import dataclass

import process_registry
from governance import ad
from ui.shared.formatting import enumerate_list, pluralize


@dataclass(frozen=True)
class User:
    """The signed-in human, from the UI's point of view."""

    upn: str
    display_name: str
    can_upload: bool
    can_confirm: bool

    @property
    def view_only(self) -> bool:
        return not (self.can_upload or self.can_confirm)

    @property
    def capabilities(self) -> str:
        """One sentence instead of two checkmarks -- and with the document
        kinds spelled out.

        "Sie können Belege hochladen" leaves open *which*. The answer lives
        in the process registry and is spelled out here, so no one has to
        find out by trial and error what the system accepts.
        """
        kinds = enumerate_list([pluralize(a) for a in process_registry.document_kinds()],
                               connector="oder")

        if self.can_upload and self.can_confirm:
            return (f"Sie können {kinds} hochladen und Vorgänge bestätigen.")
        if self.can_upload:
            return f"Sie können {kinds} hochladen."
        if self.can_confirm:
            return ("Sie können Vorgänge bestätigen, aber keine Belege "
                    "hochladen.")
        return "Sie können Vorgänge ansehen, aber keine Belege hochladen."

    @property
    def rights_short(self) -> str:
        """Short form for the badge -- terse and action-oriented.

        Deliberately WITHOUT document kinds: those belong in the full
        sentence (`capabilities`), not the badge. Two reasons against
        repeating them here:

        1. Redundancy -- the sentence already says it in full.
        2. Length -- every other badge in the system (case status like
           "Abgeschlossen" or "Wartet auf Bestätigung") is one to three
           words long. A document-kind list plus a verb breaks that
           pattern.

        What counts here is the action: "Hochladen" and "Bestätigen" are
        business-wise very different rights (four-eyes separation) and must
        remain distinguishable in the badge itself.
        """
        if self.can_upload and self.can_confirm:
            return "Beides"
        if self.can_upload:
            return "Hochladen"
        if self.can_confirm:
            return "Bestätigen"
        return "Nur lesen"

    @property
    def label_pending(self) -> str:
        """Metric label for waiting cases.

        For an authorized person, the number is a task list; for everyone
        else, a status figure. Using the same word for both would either be
        a wrong call to action or a wasted one.
        """
        return ("Warten auf Ihre Bestätigung" if self.can_confirm
                else "Warten auf Bestätigung")

    # --- Reasons for blocked actions ----------------------------------------
    # Always the same pattern: what does not work, and what to do about it.
    # Never with the name of a security group -- that helps no one who
    # cannot manage it anyway.

    @property
    def upload_hint(self) -> str:
        kinds = enumerate_list([pluralize(a) for a in process_registry.document_kinds()],
                               connector="oder")
        return (f"Ihr Konto ist nicht berechtigt, {kinds} hochzuladen. "
                "Wenden Sie sich an Ihre IT, wenn Sie diese Berechtigung "
                "benötigen.")

    @property
    def confirm_hint(self) -> str:
        return ("Diesen Vorgang kann nur eine dafür berechtigte Person "
                "bestätigen. Ihr Konto hat diese Berechtigung nicht.")

    @property
    def own_document_hint(self) -> str:
        return ("Sie haben diesen Beleg selbst hochgeladen. Vorgesehen ist, "
                "dass eine zweite Person ihn bestätigt.")


def load(con: sqlite3.Connection, upn: str) -> User:
    """Builds the user context from the directory service.

    An unknown account is not an error but an account without rights -- the
    UI should be able to display it instead of crashing.
    """
    try:
        ad_user = ad.load_user(con, upn)
        display_name = ad_user.display_name
    except ad.UnknownUser:
        display_name = upn

    return User(
        upn=upn,
        display_name=display_name,
        can_upload=ad.check_reader_access(con, upn).allowed,
        can_confirm=ad.check_approval_permission(con, upn).allowed,
    )
