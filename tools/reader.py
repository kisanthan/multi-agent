"""Reader-Tool: PDF -> Markdown. Deterministisch, KEIN KI-Agent.

Zwei Aussagen der Arbeit stecken in diesem Modul:

1. **Kein Frontier-LLM fuers Parsing.** Ein spezialisierter, on-premise-faehiger
   Parser genuegt. Der Parser ist per Konfiguration umschaltbar
   (PyMuPDF4LLM | Docling), damit die Alternative demonstrierbar bleibt.

2. **Least Privilege als Eintrittsbedingung.** Der AD-Check liegt *innerhalb*
   von `lies_dokument()` und nicht davor. Laege er im aufrufenden Graph-Knoten,
   gaebe es einen Pfad, das PDF ohne Berechtigungspruefung zu parsen -- und
   Szenario 5 wuerde nur belegen, dass der Graph brav ist, nicht dass das Tool
   geschuetzt ist.
"""

from __future__ import annotations

import hashlib
import sqlite3
from dataclasses import dataclass
from pathlib import Path

from config import ReaderParser, einstellungen
from governance import policy
from governance.audit import OHNE_BEZUG, Entscheidung, Vorgangsbezug, protokolliere


class ZugriffVerweigert(Exception):
    """Der Einspeiser ist nicht Mitglied der AD-Sicherheitsgruppe.

    Bewusst eine Exception: ein leeres Ergebnis koennte ein Aufrufer
    versehentlich als "Dokument war halt leer" weiterverarbeiten.
    """


@dataclass(frozen=True)
class Dokumentinhalt:
    dateiname: str
    markdown: str
    dokument_hash: str
    parser: str
    seiten: int


def _hash(pfad: Path) -> str:
    """SHA-256 des Rohdokuments -- Grundlage der revisionssicheren Ablage."""
    return hashlib.sha256(pfad.read_bytes()).hexdigest()


def _parse_pymupdf4llm(pfad: Path) -> tuple[str, int]:
    import pymupdf
    import pymupdf4llm

    with pymupdf.open(pfad) as doc:
        seiten = doc.page_count
    return pymupdf4llm.to_markdown(str(pfad), show_progress=False), seiten


def _parse_docling(pfad: Path) -> tuple[str, int]:
    """Alternativer Pfad: spezialisierter On-Premise-Parser (IBM Docling, MIT).

    Nicht der Default -- Docling laedt beim ersten Lauf 1-2 GB Modellgewichte,
    was fuer die hier verwendeten nativen (nicht gescannten) PDFs keinen
    Mehrwert bringt. Der Umschalter existiert, damit die Arbeit den Vergleich
    zeigen kann.
    """
    try:
        from docling.document_converter import DocumentConverter
    except ImportError as e:
        raise RuntimeError(
            "READER_PARSER=docling gesetzt, aber Docling ist nicht installiert. "
            "Installation: pip install docling  (laedt ~1-2 GB Modellgewichte)."
        ) from e

    ergebnis = DocumentConverter().convert(str(pfad))
    return ergebnis.document.export_to_markdown(), len(ergebnis.document.pages)


def lies_dokument(con: sqlite3.Connection, pfad: Path | str, *, akteur: str,
                  bezug: Vorgangsbezug = OHNE_BEZUG) -> Dokumentinhalt:
    """Nimmt ein PDF entgegen und liefert LLM-taugliches Markdown.

    Der AD-Check ist die erste Anweisung -- vor jedem Dateizugriff. Ein
    verweigerter Zugriff erzeugt einen Audit-Eintrag und wirft; es wird weder
    gelesen noch geparst noch ein Modell aufgerufen.
    """
    pfad = Path(pfad)
    # Die Datenquelle steht fest, sobald der Pfad bekannt ist -- auch bei
    # verweigertem Zugriff muss im Trail stehen, *worauf* zugegriffen werden
    # sollte.
    bezug = Vorgangsbezug(bezug.vorgang_id, bezug.datenquelle or pfad.name)

    entscheid = policy.pruefe_reader_zugriff(con, akteur=akteur)
    if not entscheid.erlaubt:
        protokolliere(
            con, akteur=akteur, agent="reader", aktion="dokument_einspeisen",
            entscheidung=Entscheidung.VERWEIGERT, begruendung=entscheid.begruendung,
            payload={"datei": pfad.name, "regel": entscheid.regel},
            bezug=bezug, ergebnis="zugriff_verweigert",
        )
        con.commit()
        raise ZugriffVerweigert(entscheid.begruendung)

    if not pfad.is_file():
        raise FileNotFoundError(f"Dokument nicht gefunden: {pfad}")

    parser = einstellungen.reader_parser
    if parser is ReaderParser.DOCLING:
        markdown, seiten = _parse_docling(pfad)
    else:
        markdown, seiten = _parse_pymupdf4llm(pfad)

    dok_hash = _hash(pfad)
    protokolliere(
        con, akteur=akteur, agent="reader", aktion="dokument_eingespeist",
        entscheidung=Entscheidung.ERLAUBT, begruendung=entscheid.begruendung,
        payload={"datei": pfad.name, "dokument_hash": dok_hash,
                 "parser": parser.value, "seiten": seiten},
        bezug=bezug, ergebnis=f"{seiten} Seite(n) gelesen",
    )
    con.commit()

    return Dokumentinhalt(
        dateiname=pfad.name, markdown=markdown, dokument_hash=dok_hash,
        parser=parser.value, seiten=seiten,
    )
