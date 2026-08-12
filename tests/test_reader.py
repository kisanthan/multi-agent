"""Tests of the reader tool -- Least Privilege proof (scenario 5).

The most important test here is test_denied_access_never_reads_the_file: it
proves that on missing AD membership, not just an error occurs, but the
document is in fact never opened. "Access denied" and "access denied, but
quickly read first" look the same from outside -- this test tells them
apart.
"""

from __future__ import annotations

from pathlib import Path
from unittest.mock import patch

import pytest

from governance.audit import read_all, verify_chain
from tools.reader import DocumentContent, AccessDenied, read_document

SUBMITTER = "einspeiser@chg-meridian.com"
EXTERNAL = "extern@partner.de"

PDF = Path(__file__).parent.parent / "data" / "inbox" / "A_payment_ok_01.pdf"

pytestmark = pytest.mark.skipif(
    not PDF.is_file(),
    reason="Testdaten fehlen -- zuerst `python -m data.generate` ausfuehren.",
)


def test_authorized_submitter_gets_markdown(con):
    content = read_document(con, PDF, actor=SUBMITTER)

    assert isinstance(content, DocumentContent)
    assert content.parser == "pymupdf4llm"
    assert content.pages == 1
    assert len(content.document_hash) == 64
    # The business-critical fields must make it into the markdown.
    assert "Zahlungsbestaetigung" in content.markdown
    assert "Verwendungszweck" in content.markdown


def test_unauthorized_submitter_is_denied(con):
    with pytest.raises(AccessDenied, match="SG-CHG-DocIngest"):
        read_document(con, PDF, actor=EXTERNAL)


def test_unknown_user_is_denied(con):
    """Zero Trust: no AD entry, no access."""
    with pytest.raises(AccessDenied):
        read_document(con, PDF, actor="niemand@nirgends.de")


def test_denied_access_never_reads_the_file(con):
    """Core Least Privilege proof: the parser is never reached.

    We patch the parser: if it were called despite the denied AD check, the
    test fails. That proves the check sits *before* any file access and
    does not just discard the result.
    """
    with patch("tools.reader._parse_pymupdf4llm") as parser:
        with pytest.raises(AccessDenied):
            read_document(con, PDF, actor=EXTERNAL)
        parser.assert_not_called()


def test_denied_access_creates_an_audit_entry(con):
    """Scenario 5 requires exactly that: denied *and* logged."""
    with pytest.raises(AccessDenied):
        read_document(con, PDF, actor=EXTERNAL)

    entries = read_all(con)
    assert len(entries) == 1
    e = entries[0]
    assert e.agent == "reader"
    assert e.action == "dokument_einspeisen"
    assert e.decision.value == "verweigert"
    assert e.actor == EXTERNAL
    assert verify_chain(con).valid


def test_successful_access_logs_document_hash(con):
    """The hash is the basis for the tamper-evident filing in process B."""
    content = read_document(con, PDF, actor=SUBMITTER)

    entries = read_all(con)
    assert entries[-1].action == "dokument_eingespeist"
    assert entries[-1].decision.value == "erlaubt"
    assert verify_chain(con).valid
    # Same document -> same hash (duplicate detection in process A).
    assert read_document(con, PDF, actor=SUBMITTER).document_hash == content.document_hash


def test_missing_file_reports_clearly(con):
    with pytest.raises(FileNotFoundError):
        read_document(con, PDF.parent / "gibt_es_nicht.pdf", actor=SUBMITTER)
