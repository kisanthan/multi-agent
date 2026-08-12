"""What the signed-in human may do -- in words they understand.

The governance layer answers precisely and technically: "X is not a member
of security group SG-CHG-Freigabe (Least Privilege)". That is exactly right
as an audit entry and useless as on-screen text.

This module is the translation layer between the two. It decides nothing --
the rules stay in `governance/` -- it only phrases what they mean, and
which hints make sense on which page at all.

The wording itself lives in `ui/locales/`; every property below picks a key
and fills it in. Nothing here is language-specific except that choice.
"""

from __future__ import annotations

import sqlite3
from dataclasses import dataclass

from governance import ad
from ui.shared import i18n
from ui.shared.formatting import enumerate_list


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
    def _document_kinds(self) -> str:
        """The document kinds, spelled out and joined with "or".

        "Sie können Belege hochladen" leaves open *which*. The answer lives
        in the process registry and is spelled out here, so no one has to
        find out by trial and error what the system accepts.
        """
        return enumerate_list(i18n.document_kinds_plural(),
                              connector=i18n.t("word.or"))

    @property
    def capabilities(self) -> str:
        """One sentence instead of two checkmarks."""
        if self.can_upload and self.can_confirm:
            return i18n.t("user.capabilities.both", kinds=self._document_kinds)
        if self.can_upload:
            return i18n.t("user.capabilities.upload", kinds=self._document_kinds)
        if self.can_confirm:
            return i18n.t("user.capabilities.confirm")
        return i18n.t("user.capabilities.view")

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
            return i18n.t("user.rights.both")
        if self.can_upload:
            return i18n.t("user.rights.upload")
        if self.can_confirm:
            return i18n.t("user.rights.confirm")
        return i18n.t("user.rights.view")

    @property
    def label_pending(self) -> str:
        """Metric label for waiting cases.

        For an authorized person, the number is a task list; for everyone
        else, a status figure. Using the same word for both would either be
        a wrong call to action or a wasted one.
        """
        return i18n.t("user.pending.own" if self.can_confirm
                      else "user.pending.other")

    # --- Reasons for blocked actions ----------------------------------------
    # Always the same pattern: what does not work, and what to do about it.
    # Never with the name of a security group -- that helps no one who
    # cannot manage it anyway.

    @property
    def upload_hint(self) -> str:
        return i18n.t("user.hint.upload", kinds=self._document_kinds)

    @property
    def confirm_hint(self) -> str:
        return i18n.t("user.hint.confirm")

    @property
    def own_document_hint(self) -> str:
        return i18n.t("user.hint.own_document")


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
