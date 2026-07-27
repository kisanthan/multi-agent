"""Policy-/Governance-Komponente: deterministisches RBAC/ABAC-Enforcement.

Die zentrale technische Aussage der Arbeit: Berechtigungs- und
Policy-Pruefungen laufen als regulaere Logik, NICHT im Sprachmodell
(Abschnitt 7 des Fachkonzepts). Dieses Modul importiert daher weder einen
LLM-Client noch irgendetwas aus `agents/` -- tests/test_schichtgrenze.py
erzwingt das.

Der praktische Beleg: jede Entscheidung hier ist mit einem Unit-Test
reproduzierbar pruefbar. Bei einem Sprachmodell waere sie das nicht.
"""

from __future__ import annotations

import sqlite3
from dataclasses import dataclass, field
from enum import Enum

from governance import ad
from registry import Aufsichtsmodus, Autonomiestufe, konfiguration


class Ergebnis(str, Enum):
    ERLAUBT = "erlaubt"
    FREIGABE_NOETIG = "freigabe_noetig"
    VERWEIGERT = "verweigert"


@dataclass(frozen=True)
class Entscheid:
    """Das Ergebnis einer Policy-Pruefung.

    `regel` benennt die Regel, die gegriffen hat. Das ist kein Logging-Luxus:
    im Audit-Trail steht damit nicht nur *dass* etwas verweigert wurde, sondern
    *warum* -- und das ist die Nachvollziehbarkeit, die die Arbeit fordert.
    """

    ergebnis: Ergebnis
    regel: str
    begruendung: str
    kontext: dict = field(default_factory=dict)

    @property
    def erlaubt(self) -> bool:
        return self.ergebnis is Ergebnis.ERLAUBT

    @property
    def braucht_freigabe(self) -> bool:
        return self.ergebnis is Ergebnis.FREIGABE_NOETIG

    def __str__(self) -> str:
        return f"[{self.ergebnis.value}] {self.regel}: {self.begruendung}"


def pruefe_schreibaktion(
    con: sqlite3.Connection,
    *,
    agent_id: str,
    akteur: str,
    aktion: str,
    betrag_eur: float | None = None,
) -> Entscheid:
    """Vorgeschaltete Pruefung vor JEDER Schreibaktion.

    Die Regeln werden in dieser Reihenfolge geprueft; die erste, die greift,
    entscheidet. Die Reihenfolge ist bewusst restriktiv-zuerst: die
    Autonomiestufe wird geprueft, bevor der Betrag ueberhaupt betrachtet wird,
    damit ein Agent der Stufe 1 auch bei 0 EUR nicht schreiben kann.
    """
    cfg = konfiguration(agent_id)
    basis = {"agent": agent_id, "akteur": akteur, "aktion": aktion,
             "autonomiestufe": cfg.autonomiestufe.value if cfg.autonomiestufe else None,
             "aufsicht": cfg.aufsicht.value}

    # Regel 1 -- Zero Trust: unbekannte Akteure brechen den Vorgang ab.
    try:
        nutzer = ad.lade_nutzer(con, akteur)
    except ad.UnbekannterNutzer as e:
        return Entscheid(Ergebnis.VERWEIGERT, "zero_trust", str(e), basis)

    # Regel 2 -- Least Privilege: Komponenten ohne Schreibrecht schreiben nie.
    if not cfg.darf_schreiben:
        return Entscheid(
            Ergebnis.VERWEIGERT, "least_privilege",
            f"{cfg.name} hat kein Schreibrecht (Typ {cfg.typ.value}).", basis,
        )

    # Regel 3 -- Autonomiestufe: Stufe 1 (Lesen) und 2 (Vorschlag) duerfen
    # nicht ausfuehren, unabhaengig von allem anderen.
    if cfg.autonomiestufe is None or cfg.autonomiestufe < Autonomiestufe.REVERSIBLES_SCHREIBEN:
        stufe = cfg.autonomiestufe.value if cfg.autonomiestufe else "keine"
        return Entscheid(
            Ergebnis.VERWEIGERT, "autonomiestufe",
            f"{cfg.name} hat Autonomiestufe {stufe}; Schreiben erfordert "
            f"mindestens Stufe {Autonomiestufe.REVERSIBLES_SCHREIBEN.value}.", basis,
        )

    # Regel 4 -- Aufsichtsmodus aus der Registry.
    # Der Buchungs-Agent ist Human-in-the-loop (Thesis §7.4): der finanzwirksame
    # Buchungsschritt erfordert immer eine menschliche Freigabe, unabhaengig vom
    # Betrag. Eine betragsbasierte Schwelle gibt es bewusst nicht -- das waere
    # eine Abschwaechung der im Konzept geforderten durchgaengigen Aufsicht.
    if cfg.aufsicht is Aufsichtsmodus.HUMAN_IN_THE_LOOP:
        kontext = {**basis, "betrag_eur": betrag_eur}
        return Entscheid(
            Ergebnis.FREIGABE_NOETIG, "aufsichtsmodus",
            f"{cfg.name} ist Human-in-the-loop -- Freigabe erforderlich.", kontext,
        )
    if cfg.aufsicht is Aufsichtsmodus.HUMAN_ON_THE_LOOP:
        return Entscheid(
            Ergebnis.ERLAUBT, "aufsichtsmodus",
            f"{cfg.name} ist Human-on-the-loop -- Ausfuehrung mit Audit-Eintrag.",
            basis,
        )

    # Regel 5 -- Default deny. Ein nicht abgedeckter Aufsichtsmodus ist ein
    # Konfigurationsfehler und darf nicht als Erlaubnis durchgehen.
    return Entscheid(
        Ergebnis.VERWEIGERT, "default_deny",
        f"Aufsichtsmodus {cfg.aufsicht.value} deckt keine Schreibaktion ab.", basis,
    )


def pruefe_freigabe(con: sqlite3.Connection, *, akteur: str, agent_id: str) -> Entscheid:
    """Prueft, ob ein Mensch einen HITL-Punkt entscheiden darf (Vier-Augen-Prinzip)."""
    cfg = konfiguration(agent_id)
    ergebnis = ad.pruefe_freigabe_berechtigung(con, akteur)
    kontext = {"agent": agent_id, "akteur": akteur, "aufsicht": cfg.aufsicht.value}
    if not ergebnis.erlaubt:
        return Entscheid(Ergebnis.VERWEIGERT, "freigabe_rbac", ergebnis.begruendung, kontext)
    return Entscheid(Ergebnis.ERLAUBT, "freigabe_rbac", ergebnis.begruendung, kontext)


def pruefe_reader_zugriff(con: sqlite3.Connection, *, akteur: str) -> Entscheid:
    """Eintrittsbedingung ins Reader-Tool (Szenario 5, Governance-Demo)."""
    ergebnis = ad.pruefe_reader_zugriff(con, akteur)
    kontext = {"agent": "reader", "akteur": akteur, "gruppe": ad.READER_GRUPPE}
    if not ergebnis.erlaubt:
        return Entscheid(Ergebnis.VERWEIGERT, "reader_rbac", ergebnis.begruendung, kontext)
    return Entscheid(Ergebnis.ERLAUBT, "reader_rbac", ergebnis.begruendung, kontext)
