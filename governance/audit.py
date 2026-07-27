"""Audit-/Monitoring-Komponente: hash-verketteter, append-only Audit-Trail.

Belegt das Evaluationskriterium "Nachvollziehbarkeit" der Arbeit. Jeder Eintrag
hasht seinen Vorgaenger; `verify_chain()` erkennt daher jede nachtraegliche
Aenderung, jede Loeschung und jede Einfuegung -- nicht nur die Aenderung selbst,
sondern auch, ab welcher Stelle die Kette bricht.

Kein LLM. Reine Python-Logik (Kap. 3.4 / Abschnitt 7 des Fachkonzepts).
"""

from __future__ import annotations

import hashlib
import json
import sqlite3
from dataclasses import dataclass
from datetime import datetime, timezone
from enum import Enum

GENESIS_HASH = "0" * 64


class Entscheidung(str, Enum):
    ERLAUBT = "erlaubt"
    VERWEIGERT = "verweigert"
    INFO = "info"


@dataclass(frozen=True)
class AuditEintrag:
    id: int
    ts: str
    akteur: str
    agent: str | None
    aktion: str
    entscheidung: Entscheidung
    begruendung: str
    payload_hash: str
    prev_hash: str
    hash: str


def _kanonisch(payload: dict) -> str:
    """Serialisiert deterministisch.

    sort_keys ist hier nicht Kosmetik: ohne stabile Schluesselreihenfolge
    haengt der Hash von der Einfuegereihenfolge im dict ab und die Kette waere
    nicht reproduzierbar pruefbar.
    """
    return json.dumps(payload, sort_keys=True, ensure_ascii=False, separators=(",", ":"))


def _payload_hash(payload: dict) -> str:
    return hashlib.sha256(_kanonisch(payload).encode("utf-8")).hexdigest()


def _eintrag_hash(ts: str, akteur: str, agent: str | None, aktion: str,
                  entscheidung: str, begruendung: str, payload_hash: str,
                  prev_hash: str) -> str:
    """Hasht den vollstaendigen Eintragsinhalt inklusive Vorgaenger-Hash.

    Alle inhaltlichen Felder gehen ein -- wuerde nur payload_hash verkettet,
    liessen sich Akteur oder Entscheidung unbemerkt aendern.
    """
    material = "|".join([
        ts, akteur, agent or "", aktion, entscheidung, begruendung,
        payload_hash, prev_hash,
    ])
    return hashlib.sha256(material.encode("utf-8")).hexdigest()


def letzter_hash(con: sqlite3.Connection) -> str:
    row = con.execute("SELECT hash FROM audit ORDER BY id DESC LIMIT 1").fetchone()
    return row[0] if row else GENESIS_HASH


def protokolliere(con: sqlite3.Connection, *, akteur: str, aktion: str,
                  entscheidung: Entscheidung, begruendung: str,
                  agent: str | None = None, payload: dict | None = None) -> AuditEintrag:
    """Haengt einen Eintrag an die Kette an.

    Bewusst ohne `commit()`: der Aufrufer entscheidet ueber die
    Transaktionsgrenze, damit Buchung und Audit-Eintrag gemeinsam gueltig
    werden oder gemeinsam zurueckrollen.
    """
    payload = payload or {}
    ts = datetime.now(timezone.utc).isoformat()
    p_hash = _payload_hash(payload)
    prev = letzter_hash(con)
    h = _eintrag_hash(ts, akteur, agent, aktion, entscheidung.value, begruendung, p_hash, prev)

    cur = con.execute(
        "INSERT INTO audit (ts, akteur, agent, aktion, entscheidung, begruendung,"
        " payload_hash, prev_hash, hash) VALUES (?,?,?,?,?,?,?,?,?)",
        (ts, akteur, agent, aktion, entscheidung.value, begruendung, p_hash, prev, h),
    )
    return AuditEintrag(
        id=cur.lastrowid, ts=ts, akteur=akteur, agent=agent, aktion=aktion,
        entscheidung=entscheidung, begruendung=begruendung,
        payload_hash=p_hash, prev_hash=prev, hash=h,
    )


@dataclass(frozen=True)
class Pruefergebnis:
    gueltig: bool
    geprueft: int
    bruch_bei: int | None = None
    grund: str | None = None

    def __str__(self) -> str:
        if self.gueltig:
            return f"Audit-Kette intakt ({self.geprueft} Eintraege)"
        return f"Audit-Kette gebrochen bei Eintrag {self.bruch_bei}: {self.grund}"


def verify_chain(con: sqlite3.Connection) -> Pruefergebnis:
    """Prueft die Hash-Kette vollstaendig.

    Der Manipulationsnachweis der Arbeit. Zwei Pruefungen pro Eintrag:
    1. Verweist prev_hash auf den tatsaechlichen Vorgaenger? (Loeschen/Einfuegen)
    2. Passt der gespeicherte Hash zum Inhalt?               (Aendern)
    """
    rows = con.execute(
        "SELECT id, ts, akteur, agent, aktion, entscheidung, begruendung,"
        " payload_hash, prev_hash, hash FROM audit ORDER BY id"
    ).fetchall()

    erwarteter_prev = GENESIS_HASH
    for i, r in enumerate(rows):
        (eid, ts, akteur, agent, aktion, entscheidung, begruendung,
         p_hash, prev_hash, h) = r

        if prev_hash != erwarteter_prev:
            return Pruefergebnis(
                False, i, eid,
                f"prev_hash verweist nicht auf den Vorgaenger "
                f"(erwartet {erwarteter_prev[:12]}..., gefunden {prev_hash[:12]}...). "
                "Deutet auf einen geloeschten oder eingefuegten Eintrag hin.",
            )

        neu = _eintrag_hash(ts, akteur, agent, aktion, entscheidung, begruendung,
                            p_hash, prev_hash)
        if neu != h:
            return Pruefergebnis(
                False, i, eid,
                f"Inhalt passt nicht zum gespeicherten Hash "
                f"(erwartet {neu[:12]}..., gefunden {h[:12]}...). "
                "Deutet auf eine nachtraegliche Aenderung hin.",
            )
        erwarteter_prev = h

    return Pruefergebnis(True, len(rows))


def lies_alle(con: sqlite3.Connection, limit: int | None = None) -> list[AuditEintrag]:
    """Read-only-Zugriff auf den Trail (Aufsichtsmodus der Audit-Komponente)."""
    sql = ("SELECT id, ts, akteur, agent, aktion, entscheidung, begruendung,"
           " payload_hash, prev_hash, hash FROM audit ORDER BY id")
    if limit:
        sql += f" LIMIT {int(limit)}"
    return [
        AuditEintrag(
            id=r[0], ts=r[1], akteur=r[2], agent=r[3], aktion=r[4],
            entscheidung=Entscheidung(r[5]), begruendung=r[6],
            payload_hash=r[7], prev_hash=r[8], hash=r[9],
        )
        for r in con.execute(sql).fetchall()
    ]
