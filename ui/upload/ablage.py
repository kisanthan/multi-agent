"""Hochgeladene Dateien pruefen und in den Eingang legen.

Getrennt von der Seite gehalten: die Pruefregeln sind fachlich und ohne
Streamlit testbar. Die Seite sammelt nur ein, was der Nutzer waehlt, und zeigt
an, was hier entschieden wurde.

Ein Upload ist noch kein Vorgang. Er legt die Datei bereit und haelt fest, wer
sie wann eingespeist hat; die Verarbeitung startet der Nutzer bewusst danach.
"""

from __future__ import annotations

import hashlib
import sqlite3
import uuid
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

from config import EINGANG_DIR
from governance.audit import Entscheidung, Vorgangsbezug, protokolliere

ERLAUBTE_ENDUNGEN = frozenset({".pdf"})
MAX_BYTES = 200 * 1024 * 1024      # entspricht server.maxUploadSize
PDF_KENNUNG = b"%PDF-"


@dataclass(frozen=True)
class Pruefung:
    """Ergebnis der Eingangspruefung einer einzelnen Datei."""

    ok: bool
    grund: str
    dublette_von: str | None = None   # upload_id einer inhaltsgleichen Datei

    @property
    def ist_dublette(self) -> bool:
        return self.dublette_von is not None


@dataclass(frozen=True)
class Upload:
    upload_id: str
    dateiname: str
    pfad: str
    dateityp: str
    groesse_bytes: int
    inhalt_hash: str
    hochgeladen_von: str
    hochgeladen_am: str
    pruefergebnis: str


def inhalt_hash(daten: bytes) -> str:
    """SHA-256 wie im Reader-Tool -- damit dieselbe Datei dieselbe Kennung hat."""
    return hashlib.sha256(daten).hexdigest()


def pruefe(con: sqlite3.Connection, *, dateiname: str, daten: bytes) -> Pruefung:
    """Entscheidet, ob eine Datei in den Eingang darf.

    Die Reihenfolge ist absichtlich billig-zuerst: Endung und Groesse kosten
    nichts, der Datenbankzugriff auf Dubletten kommt zuletzt.
    """
    endung = Path(dateiname).suffix.lower()
    if endung not in ERLAUBTE_ENDUNGEN:
        erlaubt = ", ".join(sorted(ERLAUBTE_ENDUNGEN))
        return Pruefung(False, f"Dateien vom Typ „{endung or 'ohne Endung'}“ "
                               f"können nicht verarbeitet werden. Möglich "
                               f"sind: {erlaubt}.")

    if not daten:
        return Pruefung(False, "Die Datei enthält keine Daten.")

    if len(daten) > MAX_BYTES:
        return Pruefung(False, f"Die Datei ist größer als "
                               f"{MAX_BYTES // (1024 * 1024)} MB und damit zu "
                               f"groß.")

    # Die Endung ist eine Behauptung, die Kopfbytes sind ein Beleg. Ein als PDF
    # benanntes Bild wuerde sonst erst im Reader scheitern -- mit einer
    # Fehlermeldung, die niemand versteht.
    if not daten.startswith(PDF_KENNUNG):
        return Pruefung(False, "Die Datei ist kein PDF, auch wenn sie so heißt.")

    vorhanden = con.execute(
        "SELECT upload_id FROM uploads WHERE inhalt_hash = ?", (inhalt_hash(daten),)
    ).fetchone()
    if vorhanden:
        return Pruefung(False, "Dieser Beleg wurde bereits hochgeladen – "
                               "der Inhalt ist identisch.",
                        dublette_von=vorhanden[0])

    return Pruefung(True, "Kann übernommen werden.")


def lege_ab(con: sqlite3.Connection, *, dateiname: str, daten: bytes,
            akteur: str) -> Upload:
    """Schreibt die Datei in den Eingang und protokolliert den Upload.

    Der Aufrufer hat zuvor `pruefe()` aufgerufen -- hier wird nicht erneut
    geprueft, aber der Dateiname normalisiert: ein Pfadanteil im Namen darf
    nicht ausserhalb des Eingangsordners landen.
    """
    sicherer_name = Path(dateiname).name
    ziel = EINGANG_DIR / sicherer_name
    EINGANG_DIR.mkdir(parents=True, exist_ok=True)
    ziel.write_bytes(daten)

    upload = Upload(
        upload_id=f"UP-{uuid.uuid4().hex[:12].upper()}",
        dateiname=sicherer_name,
        pfad=str(ziel),
        dateityp=Path(sicherer_name).suffix.lower().lstrip("."),
        groesse_bytes=len(daten),
        inhalt_hash=inhalt_hash(daten),
        hochgeladen_von=akteur,
        hochgeladen_am=datetime.now(timezone.utc).isoformat(),
        pruefergebnis="bestanden",
    )

    con.execute(
        "INSERT INTO uploads (upload_id, dateiname, pfad, dateityp, groesse_bytes,"
        " inhalt_hash, hochgeladen_von, hochgeladen_am, pruefergebnis)"
        " VALUES (?,?,?,?,?,?,?,?,?)",
        (upload.upload_id, upload.dateiname, upload.pfad, upload.dateityp,
         upload.groesse_bytes, upload.inhalt_hash, upload.hochgeladen_von,
         upload.hochgeladen_am, upload.pruefergebnis),
    )
    # Der Upload ist selbst ein protokollpflichtiges Ereignis -- er gehoert noch
    # zu keinem Vorgang, aber sehr wohl zu einer Datei und einem Menschen.
    protokolliere(
        con, akteur=akteur, agent=None, aktion="datei_hochgeladen",
        entscheidung=Entscheidung.ERLAUBT,
        begruendung=f"{sicherer_name} in den Eingang übernommen.",
        payload={"upload_id": upload.upload_id, "inhalt_hash": upload.inhalt_hash,
                 "groesse_bytes": upload.groesse_bytes},
        bezug=Vorgangsbezug(None, sicherer_name), ergebnis="abgelegt",
    )
    con.commit()
    return upload


def protokolliere_abweisung(con: sqlite3.Connection, *, dateiname: str, akteur: str,
                            grund: str) -> None:
    """Auch eine abgewiesene Datei gehoert in den Trail.

    Sonst waere aus dem Protokoll nicht erkennbar, dass jemand etwas
    Unzulaessiges einspeisen wollte.
    """
    protokolliere(
        con, akteur=akteur, agent=None, aktion="datei_hochgeladen",
        entscheidung=Entscheidung.VERWEIGERT, begruendung=grund,
        payload={"dateiname": Path(dateiname).name},
        bezug=Vorgangsbezug(None, Path(dateiname).name), ergebnis="abgewiesen",
    )
    con.commit()


def lade(con: sqlite3.Connection, upload_id: str) -> Upload | None:
    row = con.execute(
        "SELECT upload_id, dateiname, pfad, dateityp, groesse_bytes, inhalt_hash,"
        " hochgeladen_von, hochgeladen_am, pruefergebnis FROM uploads"
        " WHERE upload_id = ?", (upload_id,)
    ).fetchone()
    return Upload(*row) if row else None


def fuer_datei(con: sqlite3.Connection, dateiname: str) -> Upload | None:
    """Jüngster Upload-Eintrag zu einem Dateinamen.

    Die Belege aus `data.generate` haben keinen Upload-Eintrag -- sie lagen
    schon im Ordner. Dann ist `None` die richtige Antwort, kein Fehler.
    """
    row = con.execute(
        "SELECT upload_id, dateiname, pfad, dateityp, groesse_bytes, inhalt_hash,"
        " hochgeladen_von, hochgeladen_am, pruefergebnis FROM uploads"
        " WHERE dateiname = ? ORDER BY hochgeladen_am DESC LIMIT 1", (dateiname,)
    ).fetchone()
    return Upload(*row) if row else None
