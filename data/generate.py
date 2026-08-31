"""Generator for synthetic master data and intake documents.

There is no real data (section 7 of the functional concept). Everything
here is generated. The seed is fixed so runs are reproducible -- a
requirement of the thesis, but also practical: the end-to-end scenarios
check against concrete document numbers that must stay stable.

Usage:
    python -m data.generate
    python -m data.generate --seed-bundle
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

import config

SEED = 20260717
CUTOFF_DATE = date(2026, 7, 17)

fake = Faker("de_DE")


# ------------------------------------------------------------------ Master data

# Realistic CHG cost centers. The reference (3rd column) is the unique code
# printed on the document and looked up exactly; the keywords serve only
# the exception-case display.
COST_CENTERS = [
    ("KST-1000", "IT-Infrastruktur", "KTR-ITINFRA", "server,cloud,azure,rechenzentrum,lizenz,software,hosting"),
    ("KST-1100", "Telekommunikation", "KTR-TELCO", "telefon,mobilfunk,festnetz,internet,datenleitung,voip"),
    ("KST-2000", "Vertrieb", "KTR-SALES", "crm,messe,vertrieb,kundenbesuch,provision"),
    ("KST-2100", "Marketing", "KTR-MKT", "werbung,kampagne,druck,messestand,social media"),
    ("KST-3000", "Leasing-Operations", "KTR-LEASEOPS", "leasing,refinanzierung,vertragsverwaltung,asset"),
    ("KST-3100", "Technology & Asset Management", "KTR-TAM", "hardware,notebook,refurbishment,logistik,geraet"),
    ("KST-4000", "Finanzen & Controlling", "KTR-FIN", "wirtschaftspruefung,steuerberatung,reporting,abschluss"),
    ("KST-5000", "Human Resources", "KTR-HR", "personal,recruiting,schulung,weiterbildung,zeitarbeit"),
    ("KST-6000", "Recht & Compliance", "KTR-LEGAL", "rechtsberatung,anwalt,datenschutz,revision"),
    ("KST-7000", "Facility Management", "KTR-FM", "miete,strom,reinigung,gebaeude,instandhaltung"),
]

# Fixed suppliers tied to the thesis's process examples, plus plausible
# additional IT suppliers.
SUPPLIERS = [
    ("LIF-0001", "Deutsche Telekom AG", "DE123475223", "Friedrich-Ebert-Allee 140, 53113 Bonn"),
    ("LIF-0002", "Microsoft Deutschland GmbH", "DE129415943", "Walter-Gropius-Str. 5, 80807 Muenchen"),
    ("LIF-0003", "Dell Technologies GmbH", "DE813335825", "Unterschweinstiege 10, 60549 Frankfurt"),
    ("LIF-0004", "Lenovo Deutschland GmbH", "DE813867933", "Meitnerstr. 9, 70563 Stuttgart"),
    ("LIF-0005", "Cisco Systems GmbH", "DE813040232", "Parkring 20, 85748 Garching"),
    ("LIF-0006", "SAP Deutschland SE", "DE811732811", "Hasso-Plattner-Ring 7, 69190 Walldorf"),
    ("LIF-0007", "Vodafone GmbH", "DE811221123", "Ferdinand-Braun-Platz 1, 40549 Duesseldorf"),
    ("LIF-0008", "Salesforce Germany GmbH", "DE259164145", "Erika-Mann-Str. 31, 80636 Muenchen"),
]

# AD users. Only members of SG-CHG-DocIngest may submit documents (Least
# Privilege) -- 'e.extern' is deliberately not a member.
AD_GROUPS = [
    ("SG-CHG-DocIngest", "Darf Dokumente in das Reader-Tool einspeisen"),
    ("SG-CHG-Freigabe", "Darf Klaerfaelle und Kostenstellen-Zuordnungen freigeben"),
    ("SG-CHG-Konfiguration", "Darf Agenten- und Anbieter-Einstellungen aendern"),
]

AD_USERS = [
    # (upn, display_name, role, groups)
    ("m.keller@chg-meridian.com", "Martina Keller", "einspeiser", ["SG-CHG-DocIngest"]),
    ("t.brandt@chg-meridian.com", "Tobias Brandt", "einspeiser", ["SG-CHG-DocIngest"]),
    ("s.hofmann@chg-meridian.com", "Sabine Hofmann", "pruefer",
     ["SG-CHG-DocIngest", "SG-CHG-Freigabe", "SG-CHG-Konfiguration"]),
    ("r.wagner@chg-meridian.com", "Robert Wagner", "pruefer", ["SG-CHG-Freigabe"]),
    # Not a member of the reader group -> scenario 5 (governance demo).
    ("e.extern@partner-consulting.de", "Erik Extern", "beobachter", []),
]


@dataclass
class Document:
    """A generated intake document, along with its expectation.

    The manifest is the bridge between the generator and the demo: the CLI
    runner reads from it which scenario a document represents and what the
    outcome should be. That way, the expectation lives in one place instead
    of being scattered through test code.
    """

    filename: str
    process: str            # 'A' | 'B'
    scenario: str
    submitter: str          # UPN
    incident: str | None
    expectation: str
    # Business payload to check against:
    number: str | None = None
    amount_eur: float | None = None
    supplier: str | None = None
    expected_cost_center: str | None = None
    cost_center_reference: str | None = None


def _invoice_number(i: int) -> str:
    return f"RE-2026-{4200 + i:04d}"


def generate_master_data(con: sqlite3.Connection, rng: random.Random) -> list[dict]:
    """Creates suppliers, cost centers, AD data, and 50 open invoices."""
    con.executemany("INSERT INTO suppliers VALUES (?,?,?,?)", SUPPLIERS)
    con.executemany("INSERT INTO cost_centers VALUES (?,?,?,?)", COST_CENTERS)
    con.executemany("INSERT INTO ad_groups VALUES (?,?)", AD_GROUPS)

    for upn, name, role, groups in AD_USERS:
        con.execute("INSERT INTO ad_users VALUES (?,?,?)", (upn, name, role))
        for g in groups:
            con.execute("INSERT INTO ad_memberships VALUES (?,?)", (upn, g))

    invoices = []
    for i in range(50):
        supplier = rng.choice(SUPPLIERS)[0]
        # Wide amount range on purpose: it is what lets the scenarios show
        # that the booking approval is owed regardless of amount (thesis
        # §7.4 -- there is no threshold below which booking is automatic).
        amount = round(rng.uniform(150.0, 45_000.0), 2)
        due = CUTOFF_DATE + timedelta(days=rng.randint(-30, 60))
        r = {
            "number": _invoice_number(i),
            "amount_eur": amount,
            "due_date": due.isoformat(),
            "status": "offen",
            "supplier_id": supplier,
            "paid_at": None,
        }
        invoices.append(r)
        con.execute(
            "INSERT INTO invoices VALUES (:number,:amount_eur,:due_date,"
            ":status,:supplier_id,:paid_at)",
            r,
        )
    return invoices


# --------------------------------------------------------------------- PDFs

def _format_eur(amount: float) -> str:
    """Formats an amount in German notation: 1.341,96

    Python formats in English (1,341.96). A plain replace(',', '.') would
    produce '1.341.96' -- two dots, no comma -- making the amount unreadable
    for the extraction agent. Hence the detour via a placeholder character.
    """
    return f"{amount:,.2f}".translate(str.maketrans({",": ".", ".": ","}))


def _header(c: canvas.Canvas, title: str, sender: str) -> float:
    width, height = A4
    y = height - 25 * mm
    c.setFont("Helvetica-Bold", 9)
    c.drawString(20 * mm, y, sender)
    y -= 12 * mm
    c.setFont("Helvetica-Bold", 15)
    c.drawString(20 * mm, y, title)
    y -= 10 * mm
    c.setLineWidth(0.5)
    c.line(20 * mm, y, width - 20 * mm, y)
    return y - 10 * mm


def _row(c: canvas.Canvas, y: float, label: str, value: str, bold: bool = False) -> float:
    c.setFont("Helvetica", 10)
    c.drawString(20 * mm, y, label)
    c.setFont("Helvetica-Bold" if bold else "Helvetica", 10)
    c.drawString(75 * mm, y, value)
    return y - 6 * mm


def payment_confirmation(path: Path, *, number: str, amount: float,
                         supplier_name: str, bank: str, date_: date) -> None:
    """Process A: payment confirmation with an invoice/order number."""
    c = canvas.Canvas(str(path), pagesize=A4, invariant=1)
    y = _header(c, "Zahlungsbestaetigung", bank)
    y = _row(c, y, "Buchungsdatum:", date_.strftime("%d.%m.%Y"))
    y = _row(c, y, "Auftraggeber:", "CHG-MERIDIAN AG")
    y = _row(c, y, "Empfaenger:", supplier_name)
    y -= 4 * mm
    y = _row(c, y, "Verwendungszweck:", number, bold=True)
    y = _row(c, y, "Betrag:", f"{_format_eur(amount)} EUR", bold=True)
    y -= 8 * mm
    c.setFont("Helvetica", 8)
    c.drawString(20 * mm, y, "Diese Bestaetigung wurde maschinell erstellt und ist ohne "
                             "Unterschrift gueltig.")
    c.showPage()
    c.save()


def incoming_invoice(path: Path, *, number: str, amount: float, supplier: tuple,
                     line_items: list[tuple[str, float]], date_: date,
                     cost_center_reference: str | None = None) -> None:
    """Process B: supplier invoice with line items and cost-center reference.

    The cost-center reference is the unique code the cost-center agent
    looks up exactly. If it is missing (None), an exception case results --
    the assignment is then not unique and goes to a human.
    """
    _, name, vat_id, address = supplier
    c = canvas.Canvas(str(path), pagesize=A4, invariant=1)
    y = _header(c, "Rechnung", f"{name} | {address}")
    y = _row(c, y, "Rechnungsnummer:", number, bold=True)
    y = _row(c, y, "Rechnungsdatum:", date_.strftime("%d.%m.%Y"))
    y = _row(c, y, "USt-IdNr.:", vat_id)
    y = _row(c, y, "Rechnungsempfaenger:", "CHG-MERIDIAN AG, Franz-Beer-Str. 111, 88250 Weingarten")
    if cost_center_reference:
        y = _row(c, y, "Kostenstellenreferenz:", cost_center_reference, bold=True)
    y -= 8 * mm

    c.setFont("Helvetica-Bold", 10)
    c.drawString(20 * mm, y, "Pos")
    c.drawString(32 * mm, y, "Bezeichnung")
    c.drawRightString(180 * mm, y, "Betrag (EUR)")
    y -= 2 * mm
    c.line(20 * mm, y, 190 * mm, y)
    y -= 6 * mm

    for i, (label, item_amount) in enumerate(line_items, start=1):
        c.setFont("Helvetica", 10)
        c.drawString(20 * mm, y, str(i))
        c.drawString(32 * mm, y, label)
        c.drawRightString(180 * mm, y, _format_eur(item_amount))
        y -= 6 * mm

    y -= 2 * mm
    c.line(120 * mm, y, 190 * mm, y)
    y -= 6 * mm
    c.setFont("Helvetica-Bold", 10)
    c.drawString(120 * mm, y, "Gesamtbetrag")
    c.drawRightString(180 * mm, y, _format_eur(amount))
    y -= 12 * mm
    c.setFont("Helvetica", 8)
    c.drawString(20 * mm, y, "Zahlbar innerhalb von 30 Tagen ohne Abzug.")
    c.showPage()
    c.save()


def generate_documents(invoices: list[dict], rng: random.Random,
                       intake_dir: Path) -> list[Document]:
    """Generates the intake PDFs: happy path plus deliberate incidents."""
    intake_dir.mkdir(parents=True, exist_ok=True)
    for old in intake_dir.glob("*.pdf"):
        old.unlink()

    supplier_by_id = {l[0]: l for l in SUPPLIERS}
    banks = ["Deutsche Bank AG", "Commerzbank AG", "Sparkasse Bodensee"]
    docs: list[Document] = []

    # ---- Process A, happy path: valid payment confirmations -----------------
    # Two of them are deliberately below, two above a typical threshold of
    # 10,000 EUR -- not because the threshold has any effect (booking is
    # always human-in-the-loop, Thesis §7.4, no amount-based automation), but
    # to demonstrate exactly that: the same single approval applies
    # regardless of amount (see tests/test_scenarios.py
    # ::test_scenario1_large_amount_same_single_approval).
    cheap = [r for r in invoices if r["amount_eur"] < 5_000][:2]
    expensive = [r for r in invoices if r["amount_eur"] > 20_000][:2]
    for idx, r in enumerate(cheap + expensive):
        sup = supplier_by_id[r["supplier_id"]]
        name = f"A_payment_ok_{idx + 1:02d}.pdf"
        payment_confirmation(
            intake_dir / name,
            number=r["number"], amount=r["amount_eur"], supplier_name=sup[1],
            bank=rng.choice(banks), date_=CUTOFF_DATE - timedelta(days=rng.randint(0, 5)),
        )
        docs.append(Document(
            filename=name, process="A", scenario="1_happy_path",
            submitter="m.keller@chg-meridian.com", incident=None,
            expectation="Betrag unstrittig -> HITL-Freigabe (immer, "
                       "unabhaengig vom Betrag) -> Verbuchung, Status offen "
                       "-> bezahlt",
            number=r["number"], amount_eur=r["amount_eur"], supplier=sup[1],
        ))

    # ---- Process A, incident: unknown number ---------------------------------
    name = "A_payment_unknown_number.pdf"
    unknown = "RE-2026-9999"
    payment_confirmation(
        intake_dir / name, number=unknown, amount=3_480.00,
        supplier_name="Dell Technologies GmbH", bank=banks[0], date_=CUTOFF_DATE,
    )
    docs.append(Document(
        filename=name, process="A", scenario="2_unbekannte_nummer",
        submitter="m.keller@chg-meridian.com", incident="nummer_unbekannt",
        expectation="Abgleich schlaegt fehl -> Klaerfall -> HITL-Freigabe -> Verbuchung",
        number=unknown, amount_eur=3_480.00, supplier="Dell Technologies GmbH",
    ))

    # ---- Process A, incident: duplicate --------------------------------------
    # The same number twice: the second run must recognize that the invoice
    # is already paid, instead of booking it again.
    duplicate = cheap[0]
    sup = supplier_by_id[duplicate["supplier_id"]]
    for k in (1, 2):
        name = f"A_payment_duplicate_{k}.pdf"
        payment_confirmation(
            intake_dir / name, number=duplicate["number"], amount=duplicate["amount_eur"],
            supplier_name=sup[1], bank=banks[1], date_=CUTOFF_DATE,
        )
        docs.append(Document(
            filename=name, process="A", scenario="2b_dublette",
            submitter="t.brandt@chg-meridian.com",
            incident=None if k == 1 else "dublette",
            expectation=("HITL-Freigabe -> Verbuchung" if k == 1
                        else "bereits bezahlt -> Klaerfall, keine zweite Verbuchung"),
            number=duplicate["number"], amount_eur=duplicate["amount_eur"], supplier=sup[1],
        ))

    # ---- Process A, incident: implausible amount -----------------------------
    mismatched = invoices[10]
    sup = supplier_by_id[mismatched["supplier_id"]]
    name = "A_payment_implausible_amount.pdf"
    wrong_amount = round(mismatched["amount_eur"] * 3.7, 2)
    payment_confirmation(
        intake_dir / name, number=mismatched["number"], amount=wrong_amount,
        supplier_name=sup[1], bank=banks[2], date_=CUTOFF_DATE,
    )
    docs.append(Document(
        filename=name, process="A", scenario="2c_betrag_unplausibel",
        submitter="t.brandt@chg-meridian.com", incident="betrag_abweichend",
        expectation="Betrag weicht von Stammdaten ab -> Klaerfall",
        number=mismatched["number"], amount_eur=wrong_amount, supplier=sup[1],
    ))

    # ---- Process A, incident: unauthorized submitter (scenario 5) -----------
    ok = invoices[20]
    sup = supplier_by_id[ok["supplier_id"]]
    name = "A_payment_unauthorized.pdf"
    payment_confirmation(
        intake_dir / name, number=ok["number"], amount=ok["amount_eur"],
        supplier_name=sup[1], bank=banks[0], date_=CUTOFF_DATE,
    )
    docs.append(Document(
        filename=name, process="A", scenario="5_ad_check_verweigert",
        submitter="e.extern@partner-consulting.de", incident="ad_kein_mitglied",
        expectation="AD-Check verweigert Zugriff -> Audit-Eintrag, kein Reader-Aufruf",
        number=ok["number"], amount_eur=ok["amount_eur"], supplier=sup[1],
    ))

    reference_by_cost_center = {k[0]: k[2] for k in COST_CENTERS}

    # ---- Process B, happy path: unique cost-center reference ----------------
    # Every invoice carries a unique cost-center reference that is looked up
    # exactly (no semantic matching).
    unique = [
        ("LIF-0001", [("Mobilfunk Rahmenvertrag, 250 Anschluesse", 8_450.00),
                      ("Festnetz Standort Weingarten", 1_120.00)], "KST-1100"),
        ("LIF-0002", [("Microsoft 365 E5, 1200 Lizenzen, Jahresabrechnung", 31_200.00),
                      ("Azure Cloud Hosting, Verbrauch Q2/2026", 6_740.00)], "KST-1000"),
        ("LIF-0004", [("Notebook ThinkPad T14, 40 Stueck, Hardware-Rollout", 52_000.00)],
         "KST-3100"),
    ]
    for idx, (sup_id, line_items, kst) in enumerate(unique, start=1):
        sup = supplier_by_id[sup_id]
        number = f"ER-2026-{7100 + idx:04d}"
        reference = reference_by_cost_center[kst]
        total = round(sum(p[1] for p in line_items), 2)
        name = f"B_invoice_ok_{idx:02d}.pdf"
        incoming_invoice(
            intake_dir / name, number=number, amount=total, supplier=sup,
            line_items=line_items, date_=CUTOFF_DATE - timedelta(days=rng.randint(1, 10)),
            cost_center_reference=reference,
        )
        docs.append(Document(
            filename=name, process="B", scenario="3_happy_path",
            submitter="m.keller@chg-meridian.com", incident=None,
            expectation="eindeutige Kostenstellenreferenz -> exakter Nachschlag -> "
                       "automatische Archivierung in ELO (Prozessende B)",
            number=number, amount_eur=total, supplier=sup[1],
            expected_cost_center=kst, cost_center_reference=reference,
        ))

    # ---- Process B, incident: cost-center reference missing (scenario 4) ---
    # The invoice carries NO cost-center reference. The exact lookup fails
    # -> assignment not unique -> exception case, human decides.
    sup = supplier_by_id["LIF-0006"]
    number = "ER-2026-7200"
    line_items = [
        ("SAP Lizenzverlaengerung Modul FI", 14_800.00),
        ("Anwenderschulung SAP FI, 3 Tage, 12 Teilnehmer", 9_600.00),
    ]
    total = round(sum(p[1] for p in line_items), 2)
    name = "B_invoice_without_reference.pdf"
    incoming_invoice(
        intake_dir / name, number=number, amount=total, supplier=sup,
        line_items=line_items, date_=CUTOFF_DATE - timedelta(days=3),
        cost_center_reference=None,
    )
    docs.append(Document(
        filename=name, process="B", scenario="4_kostenstelle_referenz_fehlt",
        submitter="t.brandt@chg-meridian.com", incident="kostenstelle_referenz_fehlt",
        expectation="keine Kostenstellenreferenz auf dem Beleg -> Nachschlag "
                   "scheitert -> Klaerfall, Mensch waehlt Kostenstelle",
        number=number, amount_eur=total, supplier=sup[1],
        expected_cost_center=None, cost_center_reference=None,
    ))

    return docs


def main(*, db_path: Path | None = None, intake_dir: Path | None = None,
         manifest_path: Path | None = None) -> None:
    db_path = db_path or config.DB_PATH
    intake_dir = intake_dir or config.INTAKE_DIR
    manifest_path = manifest_path or config.MANIFEST_PATH
    rng = random.Random(SEED)
    Faker.seed(SEED)

    db_path.parent.mkdir(parents=True, exist_ok=True)
    db_path.unlink(missing_ok=True)
    con = sqlite3.connect(db_path)
    con.executescript((config.DATA_DIR / "schema.sql").read_text(encoding="utf-8"))

    invoices = generate_master_data(con, rng)
    con.commit()

    docs = generate_documents(invoices, rng, intake_dir)
    manifest_path.parent.mkdir(parents=True, exist_ok=True)
    manifest_path.write_text(
        json.dumps([asdict(d) for d in docs], indent=2, ensure_ascii=False),
        encoding="utf-8",
    )
    con.close()

    print(f"Datenbank:   {db_path}")
    print(f"  Rechnungen:    {len(invoices)} (Status offen)")
    print(f"  Kostenstellen: {len(COST_CENTERS)}")
    print(f"  Lieferanten:   {len(SUPPLIERS)}")
    print(f"  AD-Nutzer:     {len(AD_USERS)}")
    print(f"Dokumente:   {intake_dir} ({len(docs)} PDFs)")
    for d in docs:
        marker = f"  [{d.incident}]" if d.incident else ""
        print(f"  {d.filename:38s} Prozess {d.process}  {d.scenario}{marker}")
    print(f"Manifest:    {manifest_path}")


def generate_seed_bundle() -> None:
    """Regenerate the small, versioned demo bundle for maintainers."""
    from data.bootstrap import DEFAULT_BUNDLE

    main(
        db_path=DEFAULT_BUNDLE.database,
        intake_dir=DEFAULT_BUNDLE.pdfs,
        manifest_path=DEFAULT_BUNDLE.manifest,
    )


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description="Synthetische Demo-Daten erzeugen")
    parser.add_argument(
        "--seed-bundle", action="store_true",
        help="versionierte Seeds unter data/demo statt Laufzeitdaten erzeugen",
    )
    arguments = parser.parse_args()
    generate_seed_bundle() if arguments.seed_bundle else main()
