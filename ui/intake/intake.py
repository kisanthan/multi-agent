"""Checking uploaded files and placing them in the intake folder.

Kept separate from the page: the check rules are business logic and
testable without Streamlit. The page only collects what the user chooses
and shows what was decided here.

An upload is not yet a case. It stages the file and records who submitted
it and when; the user deliberately starts processing afterwards.
"""

from __future__ import annotations

import hashlib
import sqlite3
import uuid
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

from config import INTAKE_DIR
from governance.audit import CaseReference, Decision, log_entry

ALLOWED_EXTENSIONS = frozenset({".pdf"})
MAX_BYTES = 200 * 1024 * 1024      # matches server.maxUploadSize
PDF_SIGNATURE = b"%PDF-"


@dataclass(frozen=True)
class CheckResult:
    """Result of the intake check for a single file.

    Two fields say the same thing on purpose. `reason` is the wording that
    goes into the audit trail on a rejection and must never be reworded --
    it is the record. `code` and `params` say *why* in a form the interface
    can translate for the person standing in front of it (see
    `ui/shared/i18n.py`); German falls back to `reason` and is therefore
    never a second copy.
    """

    ok: bool
    reason: str
    code: str = ""
    params: dict | None = None
    duplicate_of: str | None = None   # upload_id of a file with identical content

    @property
    def is_duplicate(self) -> bool:
        return self.duplicate_of is not None


@dataclass(frozen=True)
class Upload:
    upload_id: str
    filename: str
    path: str
    file_type: str
    size_bytes: int
    content_hash: str
    uploaded_by: str
    uploaded_at: str
    check_result: str


def content_hash(data: bytes) -> str:
    """SHA-256, same as in the reader tool -- so the same file gets the same ID."""
    return hashlib.sha256(data).hexdigest()


def check(con: sqlite3.Connection, *, filename: str, data: bytes) -> CheckResult:
    """Decides whether a file may enter the intake folder.

    The order is deliberately cheap-first: extension and size cost nothing,
    the database lookup for duplicates comes last.
    """
    extension = Path(filename).suffix.lower()
    if extension not in ALLOWED_EXTENSIONS:
        allowed = ", ".join(sorted(ALLOWED_EXTENSIONS))
        return CheckResult(
            False,
            f"Dateien vom Typ „{extension or 'ohne Endung'}“ können nicht "
            f"verarbeitet werden. Möglich sind: {allowed}.",
            code="wrong_type" if extension else "no_extension",
            params={"extension": extension, "allowed": allowed},
        )

    if not data:
        return CheckResult(False, "Die Datei enthält keine Daten.", code="empty")

    if len(data) > MAX_BYTES:
        limit = MAX_BYTES // (1024 * 1024)
        return CheckResult(
            False,
            f"Die Datei ist größer als {limit} MB und damit zu groß.",
            code="too_large", params={"limit": limit},
        )

    # The extension is a claim, the header bytes are evidence. An image
    # named as a PDF would otherwise only fail in the reader -- with an
    # error message no one understands.
    if not data.startswith(PDF_SIGNATURE):
        return CheckResult(False, "Die Datei ist kein PDF, auch wenn sie so heißt.",
                           code="not_a_pdf")

    existing = con.execute(
        "SELECT upload_id FROM uploads WHERE content_hash = ?", (content_hash(data),)
    ).fetchone()
    if existing:
        return CheckResult(False, "Dieser Beleg wurde bereits hochgeladen – "
                                  "der Inhalt ist identisch.",
                           code="duplicate", duplicate_of=existing[0])

    return CheckResult(True, "Kann übernommen werden.", code="ok")


def store(con: sqlite3.Connection, *, filename: str, data: bytes,
          actor: str) -> Upload:
    """Writes the file into the intake folder and logs the upload.

    The caller has already called `check()` -- this does not check again,
    but normalizes the filename: a path component in the name must not end
    up outside the intake folder.
    """
    safe_name = Path(filename).name
    target = INTAKE_DIR / safe_name
    INTAKE_DIR.mkdir(parents=True, exist_ok=True)
    target.write_bytes(data)

    upload = Upload(
        upload_id=f"UP-{uuid.uuid4().hex[:12].upper()}",
        filename=safe_name,
        path=str(target),
        file_type=Path(safe_name).suffix.lower().lstrip("."),
        size_bytes=len(data),
        content_hash=content_hash(data),
        uploaded_by=actor,
        uploaded_at=datetime.now(timezone.utc).isoformat(),
        check_result="bestanden",
    )

    con.execute(
        "INSERT INTO uploads (upload_id, filename, path, file_type, size_bytes,"
        " content_hash, uploaded_by, uploaded_at, check_result)"
        " VALUES (?,?,?,?,?,?,?,?,?)",
        (upload.upload_id, upload.filename, upload.path, upload.file_type,
         upload.size_bytes, upload.content_hash, upload.uploaded_by,
         upload.uploaded_at, upload.check_result),
    )
    # The upload is itself an event subject to logging -- it does not yet
    # belong to any case, but certainly to a file and a human.
    log_entry(
        con, actor=actor, agent=None, action="datei_hochgeladen",
        decision=Decision.ALLOWED,
        reason=f"{safe_name} in den Eingang übernommen.",
        payload={"upload_id": upload.upload_id, "content_hash": upload.content_hash,
                 "size_bytes": upload.size_bytes},
        reference=CaseReference(None, safe_name), outcome="abgelegt",
    )
    con.commit()
    return upload


def log_rejection(con: sqlite3.Connection, *, filename: str, actor: str,
                  reason: str) -> None:
    """A rejected file belongs in the trail too.

    Otherwise the log would not show that someone tried to submit something
    inadmissible.
    """
    log_entry(
        con, actor=actor, agent=None, action="datei_hochgeladen",
        decision=Decision.DENIED, reason=reason,
        payload={"filename": Path(filename).name},
        reference=CaseReference(None, Path(filename).name), outcome="abgewiesen",
    )
    con.commit()


def load(con: sqlite3.Connection, upload_id: str) -> Upload | None:
    row = con.execute(
        "SELECT upload_id, filename, path, file_type, size_bytes, content_hash,"
        " uploaded_by, uploaded_at, check_result FROM uploads"
        " WHERE upload_id = ?", (upload_id,)
    ).fetchone()
    return Upload(*row) if row else None


def for_file(con: sqlite3.Connection, filename: str) -> Upload | None:
    """Most recent upload entry for a filename.

    Documents from `data.generate` have no upload entry -- they were
    already in the folder. Then `None` is the right answer, not an error.
    """
    row = con.execute(
        "SELECT upload_id, filename, path, file_type, size_bytes, content_hash,"
        " uploaded_by, uploaded_at, check_result FROM uploads"
        " WHERE filename = ? ORDER BY uploaded_at DESC LIMIT 1", (filename,)
    ).fetchone()
    return Upload(*row) if row else None
