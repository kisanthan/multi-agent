"""Tests of the intake check.

The upload is the UI's new main action -- whatever slips through here fails
later in the reader with a message no one understands.
"""

from __future__ import annotations

import pytest

from governance.audit import read_all, verify_chain
from ui.intake import intake

PDF = b"%PDF-1.7\n%\xe2\xe3\xcf\xd3\nInhalt"
ACTOR = "einspeiser@chg-meridian.com"


@pytest.fixture(autouse=True)
def _intake_dir(tmp_path, monkeypatch):
    """Writes to a temporary directory instead of data/inbox."""
    monkeypatch.setattr(intake, "INTAKE_DIR", tmp_path / "inbox")


def test_valid_pdf_is_accepted(con):
    assert intake.check(con, filename="beleg.pdf", data=PDF).ok


def test_wrong_extension_is_rejected(con):
    result = intake.check(con, filename="bild.jpg", data=PDF)

    assert not result.ok
    assert ".jpg" in result.reason


def test_empty_file_is_rejected(con):
    result = intake.check(con, filename="leer.pdf", data=b"")

    assert not result.ok
    assert "keine Daten" in result.reason


def test_wrong_content_despite_pdf_extension(con):
    """The extension is a claim, the header bytes are the evidence."""
    result = intake.check(con, filename="getarnt.pdf", data=b"\xff\xd8\xff JPEG")

    assert not result.ok
    assert "kein PDF" in result.reason


def test_oversized_file_is_rejected(con, monkeypatch):
    monkeypatch.setattr(intake, "MAX_BYTES", 10)
    result = intake.check(con, filename="gross.pdf", data=PDF)

    assert not result.ok
    assert "größer" in result.reason


def test_store_writes_file_and_entry(con):
    upload = intake.store(con, filename="beleg.pdf", data=PDF, actor=ACTOR)

    assert (intake.INTAKE_DIR / "beleg.pdf").read_bytes() == PDF
    assert upload.uploaded_by == ACTOR
    assert upload.size_bytes == len(PDF)
    assert intake.load(con, upload.upload_id) == upload


def test_store_normalizes_path_components_in_the_name(con):
    """A path component in the filename must not lead out of the intake folder."""
    upload = intake.store(con, filename="../../geheim.pdf", data=PDF, actor=ACTOR)

    assert upload.filename == "geheim.pdf"
    assert (intake.INTAKE_DIR / "geheim.pdf").is_file()


def test_identical_content_counts_as_a_duplicate(con):
    first = intake.store(con, filename="beleg.pdf", data=PDF, actor=ACTOR)

    # Different name, same content -- the hash decides, not the name.
    result = intake.check(con, filename="kopie.pdf", data=PDF)

    assert not result.ok
    assert result.is_duplicate
    assert result.duplicate_of == first.upload_id


def test_upload_is_in_the_audit_trail(con):
    intake.store(con, filename="beleg.pdf", data=PDF, actor=ACTOR)

    entry = read_all(con)[-1]
    assert entry.action == "datei_hochgeladen"
    assert entry.source == "beleg.pdf"
    assert entry.outcome == "abgelegt"
    # An upload does not yet belong to any case.
    assert entry.case_id is None
    assert verify_chain(con).valid


def test_rejected_file_is_also_in_the_trail(con):
    """Otherwise an attempt to submit an inadmissible file would be invisible."""
    intake.log_rejection(con, filename="bild.jpg", actor=ACTOR,
                         reason="Der Dateiinhalt ist kein PDF.")

    entry = read_all(con)[-1]
    assert entry.outcome == "abgewiesen"
    assert entry.decision.value == "verweigert"


def test_for_file_finds_the_most_recent_entry(con):
    intake.store(con, filename="beleg.pdf", data=PDF, actor=ACTOR)

    assert intake.for_file(con, "beleg.pdf") is not None
    # Generated test documents were already in the folder and have no upload.
    assert intake.for_file(con, "nie_hochgeladen.pdf") is None
