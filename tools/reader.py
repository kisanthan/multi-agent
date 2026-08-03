"""Reader tool: PDF -> Markdown. Deterministic, NOT an AI agent.

Two of the thesis's claims are embedded in this module:

1. **No frontier LLM for parsing.** A specialized, on-premise-capable parser
   is sufficient. The parser is switchable via configuration
   (PyMuPDF4LLM | Docling), so the alternative remains demonstrable.

2. **Least Privilege as an entry condition.** The AD check lives *inside*
   `read_document()`, not before it. If it lived in the calling graph node,
   there would be a path to parse the PDF without a permission check -- and
   scenario 5 would only prove that the graph behaves, not that the tool
   itself is protected.
"""

from __future__ import annotations

import hashlib
import sqlite3
from dataclasses import dataclass
from pathlib import Path

from config import ReaderParser, settings
from governance import policy
from governance.audit import NO_REFERENCE, CaseReference, Decision, log_entry


class AccessDenied(Exception):
    """The submitter is not a member of the AD security group.

    Deliberately an exception: an empty result could accidentally be
    processed further by a caller as "the document was just empty".
    """


@dataclass(frozen=True)
class DocumentContent:
    filename: str
    markdown: str
    document_hash: str
    parser: str
    pages: int


def _hash(path: Path) -> str:
    """SHA-256 of the raw document -- the basis for tamper-evident filing."""
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _parse_pymupdf4llm(path: Path) -> tuple[str, int]:
    import pymupdf
    import pymupdf4llm

    with pymupdf.open(path) as doc:
        pages = doc.page_count
    return pymupdf4llm.to_markdown(str(path), show_progress=False), pages


def _parse_docling(path: Path) -> tuple[str, int]:
    """Alternative path: specialized on-premise parser (IBM Docling, MIT).

    Not the default -- Docling downloads 1-2 GB of model weights on first
    run, which adds no value for the native (not scanned) PDFs used here.
    The switch exists so the thesis can show the comparison.
    """
    try:
        from docling.document_converter import DocumentConverter
    except ImportError as e:
        raise RuntimeError(
            "READER_PARSER=docling gesetzt, aber Docling ist nicht installiert. "
            "Installation: pip install docling  (laedt ~1-2 GB Modellgewichte)."
        ) from e

    result = DocumentConverter().convert(str(path))
    return result.document.export_to_markdown(), len(result.document.pages)


def read_document(con: sqlite3.Connection, path: Path | str, *, actor: str,
                  reference: CaseReference = NO_REFERENCE) -> DocumentContent:
    """Accepts a PDF and returns LLM-ready markdown.

    The AD check is the first instruction -- before any file access. A
    denied access produces an audit entry and raises; nothing is read,
    parsed, or sent to a model.
    """
    path = Path(path)
    # The source is fixed as soon as the path is known -- even on denied
    # access, the trail must record *what* access was attempted.
    reference = CaseReference(reference.case_id, reference.source or path.name)

    decision = policy.check_reader_access(con, actor=actor)
    if not decision.allowed:
        log_entry(
            con, actor=actor, agent="reader", action="dokument_einspeisen",
            decision=Decision.DENIED, reason=decision.reason,
            payload={"datei": path.name, "regel": decision.rule},
            reference=reference, outcome="zugriff_verweigert",
        )
        con.commit()
        raise AccessDenied(decision.reason)

    if not path.is_file():
        raise FileNotFoundError(f"Dokument nicht gefunden: {path}")

    parser = settings.reader_parser
    if parser is ReaderParser.DOCLING:
        markdown, pages = _parse_docling(path)
    else:
        markdown, pages = _parse_pymupdf4llm(path)

    doc_hash = _hash(path)
    log_entry(
        con, actor=actor, agent="reader", action="dokument_eingespeist",
        decision=Decision.ALLOWED, reason=decision.reason,
        payload={"datei": path.name, "dokument_hash": doc_hash,
                 "parser": parser.value, "seiten": pages},
        reference=reference, outcome=f"{pages} Seite(n) gelesen",
    )
    con.commit()

    return DocumentContent(
        filename=path.name, markdown=markdown, document_hash=doc_hash,
        parser=parser.value, pages=pages,
    )
