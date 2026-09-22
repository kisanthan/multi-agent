# Rollen- und risikobasiertes Multi-Agenten-System

Der Prototyp demonstriert das Architekturartefakt der Masterarbeit an zwei
synthetischen internen Finanzprozessen. Prozess A verarbeitet eine
Zahlungsbestätigung bis zur kontrollierten Statusänderung `offen → bezahlt`.
Prozess B ordnet eine Eingangsrechnung einer Kostenstelle zu und archiviert
Originaldokument und Zuordnung. Navision, ELO und das lokale Verzeichnis sind
Mocks; eine Produktivintegration oder regulatorische Konformitätsbestätigung
ist nicht Bestandteil des Artefakts.

## Demonstrierter Agentenumfang

Die Demonstration instanziiert eine agentische Rollenfamilie durch einen
Klassifikationsagenten und zwei prozessspezifische Extraktionsagenten. Diese
Komponenten erzeugen ausschließlich strukturierte Vorschläge und besitzen
keine Schreibrechte in ERP oder Dokumentenmanagement. Ablaufsteuerung,
Referenzabgleich, Kostenstellenzuordnung, Buchung, Archivierung, Policy und
Audit sind deterministische Dienste. Ein optionaler Planner, Personal Agents
und freie Agent-zu-Agent-Kommunikation sind nicht Bestandteil der
Demonstration. Das Artefakt belegt damit den kontrollierten agentischen
Teilpfad der generischen Multi-Agenten-Referenzarchitektur, nicht ein
dezentral verhandelndes Multi-Agenten-System.

## Umgesetzte Kontrollarchitektur

- Der voreingestellte Demo-Modus startet ohne Login und wechselt ausschließlich
  zwischen vier benannten synthetischen Personen. Ein optionaler Admin-Modus
  bleibt für technische Prüfungen vorhanden, wird für die Masterarbeitsdemo
  aber nicht benötigt.
- Die geschlossene `StepPolicy` bindet Prozess, Schritt, Agent, Aktion,
  Werkzeug, Datenklasse, Autonomiestufe, Aufsicht und Auditpflicht. Fehlende
  oder unbekannte Kombinationen werden abgewiesen.
- Prozess A benötigt für jede Buchung eine Freigabe durch eine andere,
  weiterhin berechtigte Person. Prozess B fordert eine menschliche Auswahl
  nur an, wenn keine eindeutige Kostenstellenreferenz vorliegt.
- Eine erkannte Dublette ist kein normaler Buchungsvorschlag: Die erneute
  Buchung bleibt gesperrt. Der Prüfer kann den Fall ohne Buchung als Dublette
  schließen oder korrigierte Daten erneut validieren lassen.
- Eine endgültig schemawidrige Klassifikation wird als neutraler Klärfall
  geführt. Eine endgültig fehlgeschlagene Rechnungsextraktion muss vor dem
  Kostenstellenabgleich durch die Prüferrolle ergänzt werden.
- Vorschläge sind versioniert. Eine Freigabe ist an Vorgang, Aktion,
  Payload-Hash, Regelversion und Ablaufzeit gebunden und kann genau einmal
  verbraucht werden.
- Schreibzugriffe verwenden kurzlebige, empfängergebundene Grants und
  idempotente Ausführungskommandos. Ein Transport-Timeout wird als
  `in_doubt` behandelt und anhand des eigenen Zielsystembelegs geklärt.
- Der bestehende Audit-Hashverbund bleibt kompatibel. `audit_v2` ergänzt die
  sieben Kategorien Einreicher, Komponente, Quelle, Werkzeug,
  Regelentscheidung, Freigabe und Ergebnis.
- Standardklassifikation und Standardextraktion dürfen ausschließlich über
  das lokale Ollama-Ende auf `localhost` laufen. Eine Cloud-Layoutanalyse ist
  nur für einen zugeschnittenen, gerasterten und geprüften Ausschnitt nach
  dokumentiertem lokalen Fehlschlag möglich. Ohne separaten
  Bereitstellungsnachweis in der lokalen, nicht versionierten
  `data/layout-deployment.json` bleibt sie gesperrt.
- Archivkorrekturen erzeugen eine neue aktive Zuordnungsversion; Original und
  Historie werden nicht gelöscht.

Die fachliche Zuordnung steht in [docs/mapping.md](docs/mapping.md), die
Kontrollverträge in [docs/controlled-execution.md](docs/controlled-execution.md)
und die Grenzen des Prototyps in [docs/limitations.md](docs/limitations.md).

## Installation

Python 3.12 oder neuer wird vorausgesetzt.

```powershell
python -m venv .venv
.venv\Scripts\python.exe -m pip install -r requirements.txt
Copy-Item .env.example .env
```

Der erste Start erzeugt aus `data/demo/` eine beschreibbare Laufzeitkopie.
Zum bewussten Zurücksetzen dient:

```powershell
.venv\Scripts\python.exe -m data.generate
```

Ollama und das konfigurierte Modell werden außerhalb des Projekts
bereitgestellt. Der Sicherheitsvertrag akzeptiert für Standardinferenz nur
`localhost` beziehungsweise `127.0.0.1`.

```powershell
ollama serve
ollama pull qwen3:8b
.venv\Scripts\python.exe demo.py --check
```

## Demo-Modus und optionale technische Anmeldung

Der voreingestellte Modus ist `demo` und wird in `.env` mit `PORTAL_MODE`
festgelegt. Ein Moduswechsel
verändert nur den Eintritt in das Portal. Workflow, StepPolicy,
Fremdfreigabe, Audit, Grants und Zielsystemaufrufe verwenden in beiden Modi
denselben Code.

### Optionaler Admin-Modus

```dotenv
PORTAL_MODE=admin
PORTAL_ADMIN_EMAIL=admin@prototype.local
PORTAL_ADMIN_PASSWORD=Admin-Prototype-2026!
```

Beim ersten Start wird dieses Administratorkonto automatisch mit Upload-,
Freigabe- und Konfigurationsrecht angelegt. Das dokumentierte Startpasswort
gilt ausschließlich für den lokalen Prototyp und sollte bei einer gemeinsam
genutzten Installation sofort geändert werden:

```powershell
.venv\Scripts\python.exe -m governance.identity admin@prototype.local
```

Ein bereits geändertes Passwort wird beim nächsten Start nicht überschrieben.
Für eine echte Fremdfreigabe können weitere synthetische Konten mit jeweils
eigenem Passwort eingerichtet werden:

```powershell
.venv\Scripts\python.exe -m governance.identity m.keller@chg-meridian.com
.venv\Scripts\python.exe -m governance.identity t.brandt@chg-meridian.com
.venv\Scripts\python.exe -m governance.identity s.hofmann@chg-meridian.com
```

Für das Negativszenario kann
`e.extern@partner-consulting.de` eingerichtet werden. Dessen Anmeldung ist
gültig, der Belegzugriff wird anschließend wegen fehlender Prozessrechte
abgewiesen.

### Demo-Modus

```dotenv
PORTAL_MODE=demo
DEMO_SUBMITTER_UPN=m.keller@chg-meridian.com
DEMO_APPROVER_UPN=s.hofmann@chg-meridian.com
```

Das Portal öffnet ohne Login direkt mit den vorhandenen synthetischen Daten.
Über **Demo-Rolle** wird zwischen vier synthetischen Personen gewechselt:
Martina Keller und Jonas Becker dürfen hochladen, Sabine Hofmann darf
hochladen und freigeben, und Laura Schneider besitzt ebenfalls beide Rechte.
Das Vier-Augen-Prinzip wird weiterhin serverseitig geprüft: Auch eine Person
mit beiden Rechten kann ihren eigenen Vorschlag nicht freigeben.

Für die Vorführung der Masterarbeit ist ausschließlich der Demo-Modus
vorgesehen. Für einen
produktiven Einsatz ist ein Unternehmens-IAM mit starker Authentifizierung
und verwalteten Dienstidentitäten erforderlich.

## Start

Die lokalen Zielsystem-Mocks laufen in zwei eigenen Terminals:

```powershell
.venv\Scripts\python.exe -m uvicorn mocks.navision:app --port 8001
.venv\Scripts\python.exe -m uvicorn mocks.elo:app --port 8002
```

Danach kann die Oberfläche gestartet werden:

```powershell
.venv\Scripts\python.exe -m streamlit run ui/app.py
```

Alternativ führt die CLI im Demo-Modus ein Szenario ohne Login aus und
wechselt am Freigabepunkt in die simulierte Prüferrolle. Nur der optionale
Admin-Modus fragt Passwörter ab:

```powershell
.venv\Scripts\python.exe demo.py --liste
.venv\Scripts\python.exe demo.py --szenario 1 --pruefer s.hofmann@chg-meridian.com
.venv\Scripts\python.exe demo.py --audit
```

## Sollprozesse

| Prozess | Kontrollierter Ablauf | Zielsystem |
|---|---|---|
| A – Zahlungsbestätigung | Lesen → lokale Klassifikation/Extraktion → bei Schemafehler Klärung → exakter Abgleich → ggf. Korrektur → Fremdfreigabe jeder Buchung → Statuswechsel | Navision-Mock |
| B – Eingangsrechnung | Lesen → lokale Klassifikation/Extraktion → bei Schemafehler Feldprüfung → exakte Kostenstelle → nur bei fehlender Eindeutigkeit Fremdauswahl → Archivierung | ELO-Mock |

Prozess B schreibt nicht nach Navision; Prozess A archiviert nicht in ELO.

## Tests

```powershell
.venv\Scripts\python.exe -m pytest -q
```

Die Tests erzeugen ihren isolierten Laufzeitstand selbst; ein vorheriger
Demo-Start oder `data.generate` ist nicht erforderlich. Sie verwenden
gemockte Modellantworten und In-Process-ASGI-Zielsysteme. Besonders relevant
sind:

- `tests/test_control_contracts.py`: Identität, Freigabebindung,
  Rechteentzug, Grants, Idempotenz, Geldbeträge, Audit und Archivkorrektur.
- `tests/test_control_flows.py`: authentifizierte Ende-zu-Ende-Abläufe A/B.
- `tests/test_control_operations.py`: Stop/Fortsetzen, Wiederaufnahme und
  lokale Inferenzgrenze.
- `tests/test_layout_control.py`: Zuschneiden, Maskierungsprüfung,
  Bereitstellungsnachweis und erlaubter Cloud-Payload.
- `tests/test_portal_modes.py`: Administratorkonto, passwortloser Demo-Eintritt
  und unveränderte Fremdfreigabe im Demo-Modus.
- `tests/test_scenarios.py`: die fünf Demonstrationsszenarien.

## Struktur

```text
agents/       fachliche Agenten und deterministische Aktionen
governance/   Identität, StepPolicy, Kontrollzustand und Audit
runtime/      Tool-Gateway und atomare Zielsystemausführung
graph/        LangGraph-Orchestrierung und kontrollierte Knoten
llm/          lokale Extraktion und gesonderte Layout-Eskalation
mocks/        Navision- und ELO-Schnittstellen
data/         Stammdaten, additive Migrationen und Demo-Bundle
ui/           Streamlit-Cockpit
tests/        Vertrags-, Integrations- und Oberflächentests
docs/         Architektur, Mapping, Betrieb und Limitationen
```

Die ausführbaren Sicherheitsentscheidungen liegen in `governance/` und
`runtime/`. LangGraph-Checkpoints halten den fortsetzbaren Ablaufzustand,
sind jedoch weder Freigabe- noch Berechtigungsnachweis.
