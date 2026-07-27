"""Generator fuer synthetische Stammdaten und Eingangsdokumente.

Es gibt keine Echtdaten (Abschnitt 7 des Fachkonzepts). Alles hier ist erzeugt.
Der Seed ist fix, damit Laeufe reproduzierbar sind -- eine Anforderung der
Arbeit, aber auch praktisch: die End-to-End-Szenarien pruefen gegen konkrete
Belegnummern, die stabil bleiben muessen.

Aufruf:  python -m data.generate
"""

from __future__ import annotations

import json
import random
import sqlite3
from dataclasses import asdict, dataclass
from datetime import date, timedelta
from pathlib import Path

from faker import Faker
from reportlab.lib.pagesizes import A4
from reportlab.lib.units import mm
from reportlab.pdfgen import canvas

from config import DATA_DIR, DB_PFAD, EINGANG_DIR, MANIFEST_PFAD

SEED = 20260717
STICHTAG = date(2026, 7, 17)

fake = Faker("de_DE")


# ------------------------------------------------------------------ Stammdaten

# Realistische CHG-Kostenstellen. Die Schluesselwoerter sind die
# Zuordnungsregel, gegen die der Kostenstellen-Agent arbeitet.
KOSTENSTELLEN = [
    ("KST-1000", "IT-Infrastruktur", "server,cloud,azure,rechenzentrum,lizenz,software,hosting"),
    ("KST-1100", "Telekommunikation", "telefon,mobilfunk,festnetz,internet,datenleitung,voip"),
    ("KST-2000", "Vertrieb", "crm,messe,vertrieb,kundenbesuch,provision"),
    ("KST-2100", "Marketing", "werbung,kampagne,druck,messestand,social media"),
    ("KST-3000", "Leasing-Operations", "leasing,refinanzierung,vertragsverwaltung,asset"),
    ("KST-3100", "Technology & Asset Management", "hardware,notebook,refurbishment,logistik,geraet"),
    ("KST-4000", "Finanzen & Controlling", "wirtschaftspruefung,steuerberatung,reporting,abschluss"),
    ("KST-5000", "Human Resources", "personal,recruiting,schulung,weiterbildung,zeitarbeit"),
    ("KST-6000", "Recht & Compliance", "rechtsberatung,anwalt,datenschutz,revision"),
    ("KST-7000", "Facility Management", "miete,strom,reinigung,gebaeude,instandhaltung"),
]

# Feste Lieferanten mit Bezug zu den Prozessbeispielen der Arbeit, plus
# plausible weitere IT-Lieferanten.
LIEFERANTEN = [
    ("LIF-0001", "Deutsche Telekom AG", "DE123475223", "Friedrich-Ebert-Allee 140, 53113 Bonn"),
    ("LIF-0002", "Microsoft Deutschland GmbH", "DE129415943", "Walter-Gropius-Str. 5, 80807 Muenchen"),
    ("LIF-0003", "Dell Technologies GmbH", "DE813335825", "Unterschweinstiege 10, 60549 Frankfurt"),
    ("LIF-0004", "Lenovo Deutschland GmbH", "DE813867933", "Meitnerstr. 9, 70563 Stuttgart"),
    ("LIF-0005", "Cisco Systems GmbH", "DE813040232", "Parkring 20, 85748 Garching"),
    ("LIF-0006", "SAP Deutschland SE", "DE811732811", "Hasso-Plattner-Ring 7, 69190 Walldorf"),
    ("LIF-0007", "Vodafone GmbH", "DE811221123", "Ferdinand-Braun-Platz 1, 40549 Duesseldorf"),
    ("LIF-0008", "Salesforce Germany GmbH", "DE259164145", "Erika-Mann-Str. 31, 80636 Muenchen"),
]

# AD-Nutzer. Nur Mitglieder von SG-CHG-DocIngest duerfen einspeisen
# (Least Privilege) -- 'e.extern' ist bewusst kein Mitglied.
AD_GRUPPEN = [
    ("SG-CHG-DocIngest", "Darf Dokumente in das Reader-Tool einspeisen"),
    ("SG-CHG-Freigabe", "Darf Klaerfaelle und Kostenstellen-Zuordnungen freigeben"),
]

AD_NUTZER = [
    # (upn, anzeigename, rolle, gruppen)
    ("m.keller@chg-meridian.com", "Martina Keller", "einspeiser", ["SG-CHG-DocIngest"]),
    ("t.brandt@chg-meridian.com", "Tobias Brandt", "einspeiser", ["SG-CHG-DocIngest"]),
    ("s.hofmann@chg-meridian.com", "Sabine Hofmann", "pruefer",
     ["SG-CHG-DocIngest", "SG-CHG-Freigabe"]),
    ("r.wagner@chg-meridian.com", "Robert Wagner", "pruefer", ["SG-CHG-Freigabe"]),
    # Kein Mitglied der Reader-Gruppe -> Szenario 5 (Governance-Demo).
    ("e.extern@partner-consulting.de", "Erik Extern", "beobachter", []),
]


@dataclass
class Dokument:
    """Ein generiertes Eingangsdokument samt Erwartungshaltung.

    Das Manifest ist die Bruecke zwischen Generator und Demo: der CLI-Runner
    liest daraus, welches Szenario ein Dokument belegt und was herauskommen
    soll. So steht die Erwartung an einer Stelle statt verstreut im Testcode.
    """

    dateiname: str
    prozess: str            # 'A' | 'B'
    szenario: str
    einspeiser: str         # UPN
    stoerfall: str | None
    erwartung: str
    # Fachliche Nutzdaten, gegen die geprueft werden kann:
    nummer: str | None = None
    betrag_eur: float | None = None
    lieferant: str | None = None
    erwartete_kostenstelle: str | None = None


def _rechnungsnummer(i: int) -> str:
    return f"RE-2026-{4200 + i:04d}"


def erzeuge_stammdaten(con: sqlite3.Connection, rng: random.Random) -> list[dict]:
    """Legt Lieferanten, Kostenstellen, AD und 50 offene Rechnungen an."""
    con.executemany("INSERT INTO lieferanten VALUES (?,?,?,?)", LIEFERANTEN)
    con.executemany("INSERT INTO kostenstellen VALUES (?,?,?)", KOSTENSTELLEN)
    con.executemany("INSERT INTO ad_gruppen VALUES (?,?)", AD_GRUPPEN)

    for upn, name, rolle, gruppen in AD_NUTZER:
        con.execute("INSERT INTO ad_nutzer VALUES (?,?,?)", (upn, name, rolle))
        for g in gruppen:
            con.execute("INSERT INTO ad_mitgliedschaften VALUES (?,?)", (upn, g))

    rechnungen = []
    for i in range(50):
        lieferant = rng.choice(LIEFERANTEN)[0]
        # Breite Betragsspanne, damit die Buchungsschwelle beide Seiten sieht.
        betrag = round(rng.uniform(150.0, 45_000.0), 2)
        faellig = STICHTAG + timedelta(days=rng.randint(-30, 60))
        r = {
            "nummer": _rechnungsnummer(i),
            "betrag_eur": betrag,
            "faellig_am": faellig.isoformat(),
            "status": "offen",
            "lieferant_id": lieferant,
            "bezahlt_am": None,
        }
        rechnungen.append(r)
        con.execute(
            "INSERT INTO rechnungen VALUES (:nummer,:betrag_eur,:faellig_am,"
            ":status,:lieferant_id,:bezahlt_am)",
            r,
        )
    return rechnungen


# --------------------------------------------------------------------- PDFs

def _eur(betrag: float) -> str:
    """Formatiert einen Betrag in deutscher Notation: 1.341,96

    Python formatiert englisch (1,341.96). Ein blosses replace(',', '.') erzeugt
    '1.341.96' -- zwei Punkte, kein Komma -- und macht den Betrag fuer den
    Extraktions-Agenten unlesbar. Daher der Umweg ueber ein Platzhalterzeichen.
    """
    return f"{betrag:,.2f}".translate(str.maketrans({",": ".", ".": ","}))


def _kopf(c: canvas.Canvas, titel: str, absender: str) -> float:
    breite, hoehe = A4
    y = hoehe - 25 * mm
    c.setFont("Helvetica-Bold", 9)
    c.drawString(20 * mm, y, absender)
    y -= 12 * mm
    c.setFont("Helvetica-Bold", 15)
    c.drawString(20 * mm, y, titel)
    y -= 10 * mm
    c.setLineWidth(0.5)
    c.line(20 * mm, y, breite - 20 * mm, y)
    return y - 10 * mm


def _zeile(c: canvas.Canvas, y: float, label: str, wert: str, fett: bool = False) -> float:
    c.setFont("Helvetica", 10)
    c.drawString(20 * mm, y, label)
    c.setFont("Helvetica-Bold" if fett else "Helvetica", 10)
    c.drawString(75 * mm, y, wert)
    return y - 6 * mm


def zahlungsbestaetigung(pfad: Path, *, nummer: str, betrag: float,
                         lieferant_name: str, bank: str, datum: date) -> None:
    """Prozess A: Zahlungsbestaetigung mit Rechnungs-/Bestellnummer."""
    c = canvas.Canvas(str(pfad), pagesize=A4)
    y = _kopf(c, "Zahlungsbestaetigung", bank)
    y = _zeile(c, y, "Buchungsdatum:", datum.strftime("%d.%m.%Y"))
    y = _zeile(c, y, "Auftraggeber:", "CHG-MERIDIAN AG")
    y = _zeile(c, y, "Empfaenger:", lieferant_name)
    y -= 4 * mm
    y = _zeile(c, y, "Verwendungszweck:", nummer, fett=True)
    y = _zeile(c, y, "Betrag:", f"{_eur(betrag)} EUR", fett=True)
    y -= 8 * mm
    c.setFont("Helvetica", 8)
    c.drawString(20 * mm, y, "Diese Bestaetigung wurde maschinell erstellt und ist ohne "
                             "Unterschrift gueltig.")
    c.showPage()
    c.save()


def eingangsrechnung(pfad: Path, *, nummer: str, betrag: float, lieferant: tuple,
                     positionen: list[tuple[str, float]], datum: date) -> None:
    """Prozess B: Lieferantenrechnung mit Positionen (Kostenstellen-Referenz)."""
    _, name, ustid, adresse = lieferant
    c = canvas.Canvas(str(pfad), pagesize=A4)
    y = _kopf(c, "Rechnung", f"{name} | {adresse}")
    y = _zeile(c, y, "Rechnungsnummer:", nummer, fett=True)
    y = _zeile(c, y, "Rechnungsdatum:", datum.strftime("%d.%m.%Y"))
    y = _zeile(c, y, "USt-IdNr.:", ustid)
    y = _zeile(c, y, "Rechnungsempfaenger:", "CHG-MERIDIAN AG, Franz-Beer-Str. 111, 88250 Weingarten")
    y -= 8 * mm

    c.setFont("Helvetica-Bold", 10)
    c.drawString(20 * mm, y, "Pos")
    c.drawString(32 * mm, y, "Bezeichnung")
    c.drawRightString(180 * mm, y, "Betrag (EUR)")
    y -= 2 * mm
    c.line(20 * mm, y, 190 * mm, y)
    y -= 6 * mm

    for i, (bez, pos_betrag) in enumerate(positionen, start=1):
        c.setFont("Helvetica", 10)
        c.drawString(20 * mm, y, str(i))
        c.drawString(32 * mm, y, bez)
        c.drawRightString(180 * mm, y, _eur(pos_betrag))
        y -= 6 * mm

    y -= 2 * mm
    c.line(120 * mm, y, 190 * mm, y)
    y -= 6 * mm
    c.setFont("Helvetica-Bold", 10)
    c.drawString(120 * mm, y, "Gesamtbetrag")
    c.drawRightString(180 * mm, y, _eur(betrag))
    y -= 12 * mm
    c.setFont("Helvetica", 8)
    c.drawString(20 * mm, y, "Zahlbar innerhalb von 30 Tagen ohne Abzug.")
    c.showPage()
    c.save()


def erzeuge_dokumente(rechnungen: list[dict], rng: random.Random) -> list[Dokument]:
    """Erzeugt die Eingangs-PDFs: Happy Path plus bewusste Stoerfaelle."""
    EINGANG_DIR.mkdir(parents=True, exist_ok=True)
    for alt in EINGANG_DIR.glob("*.pdf"):
        alt.unlink()

    lieferant_nach_id = {l[0]: l for l in LIEFERANTEN}
    banken = ["Deutsche Bank AG", "Commerzbank AG", "Sparkasse Bodensee"]
    docs: list[Dokument] = []

    # ---- Prozess A, Happy Path: gueltige Zahlungsbestaetigungen -------------
    # Zwei davon liegen bewusst unter, zwei ueber einer typischen Schwelle von
    # 10.000 EUR, damit Szenario 1 beide Aufsichtsmodi zeigen kann.
    guenstig = [r for r in rechnungen if r["betrag_eur"] < 5_000][:2]
    teuer = [r for r in rechnungen if r["betrag_eur"] > 20_000][:2]
    for idx, r in enumerate(guenstig + teuer):
        lief = lieferant_nach_id[r["lieferant_id"]]
        name = f"A_zahlung_ok_{idx + 1:02d}.pdf"
        zahlungsbestaetigung(
            EINGANG_DIR / name,
            nummer=r["nummer"], betrag=r["betrag_eur"], lieferant_name=lief[1],
            bank=rng.choice(banken), datum=STICHTAG - timedelta(days=rng.randint(0, 5)),
        )
        unter_schwelle = r["betrag_eur"] < 10_000
        docs.append(Dokument(
            dateiname=name, prozess="A", szenario="1_happy_path",
            einspeiser="m.keller@chg-meridian.com", stoerfall=None,
            erwartung=("automatische Verbuchung, Status offen -> bezahlt"
                       if unter_schwelle
                       else "Betrag ueber Schwelle -> HITL-Freigabe, dann Verbuchung"),
            nummer=r["nummer"], betrag_eur=r["betrag_eur"], lieferant=lief[1],
        ))

    # ---- Prozess A, Stoerfall: unbekannte Nummer ---------------------------
    name = "A_zahlung_unbekannte_nummer.pdf"
    unbekannt = "RE-2026-9999"
    zahlungsbestaetigung(
        EINGANG_DIR / name, nummer=unbekannt, betrag=3_480.00,
        lieferant_name="Dell Technologies GmbH", bank=banken[0], datum=STICHTAG,
    )
    docs.append(Dokument(
        dateiname=name, prozess="A", szenario="2_unbekannte_nummer",
        einspeiser="m.keller@chg-meridian.com", stoerfall="nummer_unbekannt",
        erwartung="Abgleich schlaegt fehl -> Klaerfall -> HITL-Freigabe -> Verbuchung",
        nummer=unbekannt, betrag_eur=3_480.00, lieferant="Dell Technologies GmbH",
    ))

    # ---- Prozess A, Stoerfall: Dublette ------------------------------------
    # Dieselbe Nummer zweimal: der zweite Lauf muss erkennen, dass die Rechnung
    # bereits bezahlt ist, statt erneut zu verbuchen.
    dublette = guenstig[0]
    lief = lieferant_nach_id[dublette["lieferant_id"]]
    for k in (1, 2):
        name = f"A_zahlung_dublette_{k}.pdf"
        zahlungsbestaetigung(
            EINGANG_DIR / name, nummer=dublette["nummer"], betrag=dublette["betrag_eur"],
            lieferant_name=lief[1], bank=banken[1], datum=STICHTAG,
        )
        docs.append(Dokument(
            dateiname=name, prozess="A", szenario="2b_dublette",
            einspeiser="t.brandt@chg-meridian.com",
            stoerfall=None if k == 1 else "dublette",
            erwartung=("Verbuchung" if k == 1
                       else "bereits bezahlt -> Klaerfall, keine zweite Verbuchung"),
            nummer=dublette["nummer"], betrag_eur=dublette["betrag_eur"], lieferant=lief[1],
        ))

    # ---- Prozess A, Stoerfall: unplausibler Betrag -------------------------
    abweichend = rechnungen[10]
    lief = lieferant_nach_id[abweichend["lieferant_id"]]
    name = "A_zahlung_betrag_unplausibel.pdf"
    falscher_betrag = round(abweichend["betrag_eur"] * 3.7, 2)
    zahlungsbestaetigung(
        EINGANG_DIR / name, nummer=abweichend["nummer"], betrag=falscher_betrag,
        lieferant_name=lief[1], bank=banken[2], datum=STICHTAG,
    )
    docs.append(Dokument(
        dateiname=name, prozess="A", szenario="2c_betrag_unplausibel",
        einspeiser="t.brandt@chg-meridian.com", stoerfall="betrag_abweichend",
        erwartung="Betrag weicht von Stammdaten ab -> Klaerfall",
        nummer=abweichend["nummer"], betrag_eur=falscher_betrag, lieferant=lief[1],
    ))

    # ---- Prozess A, Stoerfall: unberechtigter Einspeiser (Szenario 5) ------
    ok = rechnungen[20]
    lief = lieferant_nach_id[ok["lieferant_id"]]
    name = "A_zahlung_unberechtigt.pdf"
    zahlungsbestaetigung(
        EINGANG_DIR / name, nummer=ok["nummer"], betrag=ok["betrag_eur"],
        lieferant_name=lief[1], bank=banken[0], datum=STICHTAG,
    )
    docs.append(Dokument(
        dateiname=name, prozess="A", szenario="5_ad_check_verweigert",
        einspeiser="e.extern@partner-consulting.de", stoerfall="ad_kein_mitglied",
        erwartung="AD-Check verweigert Zugriff -> Audit-Eintrag, kein Reader-Aufruf",
        nummer=ok["nummer"], betrag_eur=ok["betrag_eur"], lieferant=lief[1],
    ))

    # ---- Prozess B, Happy Path: eindeutige Kostenstellen -------------------
    eindeutig = [
        ("LIF-0001", [("Mobilfunk Rahmenvertrag, 250 Anschluesse", 8_450.00),
                      ("Festnetz Standort Weingarten", 1_120.00)], "KST-1100"),
        ("LIF-0002", [("Microsoft 365 E5, 1200 Lizenzen, Jahresabrechnung", 31_200.00),
                      ("Azure Cloud Hosting, Verbrauch Q2/2026", 6_740.00)], "KST-1000"),
        ("LIF-0004", [("Notebook ThinkPad T14, 40 Stueck, Hardware-Rollout", 52_000.00)],
         "KST-3100"),
    ]
    for idx, (lif_id, positionen, kst) in enumerate(eindeutig, start=1):
        lief = lieferant_nach_id[lif_id]
        nummer = f"ER-2026-{7100 + idx:04d}"
        gesamt = round(sum(p[1] for p in positionen), 2)
        name = f"B_rechnung_ok_{idx:02d}.pdf"
        eingangsrechnung(
            EINGANG_DIR / name, nummer=nummer, betrag=gesamt, lieferant=lief,
            positionen=positionen, datum=STICHTAG - timedelta(days=rng.randint(1, 10)),
        )
        docs.append(Dokument(
            dateiname=name, prozess="B", szenario="3_happy_path",
            einspeiser="m.keller@chg-meridian.com", stoerfall=None,
            erwartung="eindeutige Kostenstelle -> automatische Archivierung in ELO "
                      "(Prozessende B)",
            nummer=nummer, betrag_eur=gesamt, lieferant=lief[1],
            erwartete_kostenstelle=kst,
        ))

    # ---- Prozess B, Stoerfall: mehrdeutige Kostenstelle (Szenario 4) -------
    # Positionen treffen bewusst Schluesselwoerter mehrerer Kostenstellen:
    # 'schulung' -> HR, 'software'/'lizenz' -> IT-Infrastruktur.
    lief = lieferant_nach_id["LIF-0006"]
    nummer = "ER-2026-7200"
    positionen = [
        ("SAP Lizenzverlaengerung Modul FI", 14_800.00),
        ("Anwenderschulung SAP FI, 3 Tage, 12 Teilnehmer", 9_600.00),
    ]
    gesamt = round(sum(p[1] for p in positionen), 2)
    name = "B_rechnung_mehrdeutig.pdf"
    eingangsrechnung(
        EINGANG_DIR / name, nummer=nummer, betrag=gesamt, lieferant=lief,
        positionen=positionen, datum=STICHTAG - timedelta(days=3),
    )
    docs.append(Dokument(
        dateiname=name, prozess="B", szenario="4_kostenstelle_mehrdeutig",
        einspeiser="t.brandt@chg-meridian.com", stoerfall="kostenstelle_mehrdeutig",
        erwartung="Konflikt KST-1000 vs. KST-5000 -> HITL entscheidet",
        nummer=nummer, betrag_eur=gesamt, lieferant=lief[1],
        erwartete_kostenstelle=None,
    ))

    return docs


def main() -> None:
    rng = random.Random(SEED)
    Faker.seed(SEED)

    DB_PFAD.unlink(missing_ok=True)
    con = sqlite3.connect(DB_PFAD)
    con.executescript((DATA_DIR / "schema.sql").read_text(encoding="utf-8"))

    rechnungen = erzeuge_stammdaten(con, rng)
    con.commit()

    docs = erzeuge_dokumente(rechnungen, rng)
    MANIFEST_PFAD.write_text(
        json.dumps([asdict(d) for d in docs], indent=2, ensure_ascii=False),
        encoding="utf-8",
    )
    con.close()

    print(f"Datenbank:   {DB_PFAD}")
    print(f"  Rechnungen:    {len(rechnungen)} (Status offen)")
    print(f"  Kostenstellen: {len(KOSTENSTELLEN)}")
    print(f"  Lieferanten:   {len(LIEFERANTEN)}")
    print(f"  AD-Nutzer:     {len(AD_NUTZER)}")
    print(f"Dokumente:   {EINGANG_DIR} ({len(docs)} PDFs)")
    for d in docs:
        marker = f"  [{d.stoerfall}]" if d.stoerfall else ""
        print(f"  {d.dateiname:38s} Prozess {d.prozess}  {d.szenario}{marker}")
    print(f"Manifest:    {MANIFEST_PFAD}")


if __name__ == "__main__":
    main()
