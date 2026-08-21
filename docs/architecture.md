# Technische Architektur und Wartungsleitfaden

Stand: 2026-08-21 · Geltungsbereich: aktueller Prototyp im Repository

## Zweck und Dokumentationsentscheidung

Dieses Dokument erklärt die implementierte Architektur so, dass eine neue
Person den Prototyp verstehen, Fehler eingrenzen und Änderungen sicher
vornehmen kann. Es beschreibt den Code, nicht nur das fachliche Zielbild.

Eine klassische Architekturdokumentation allein wäre dafür nicht die
sinnvollste Form: Komponentenbilder erklären zwar den Aufbau, helfen aber
wenig bei pausierten LangGraph-Läufen, persistierten Verträgen, Änderungen an
einem Prozess oder Abweichungen zwischen Agentenmodell und Laufzeit. Deshalb
kombiniert dieses Dokument vier Sichten:

1. System-, Komponenten- und Abhängigkeitsstruktur,
2. tatsächliche Laufzeit- und Fehlerpfade,
3. Datenhaltung, Verträge und Sources of Truth,
4. Änderungslandkarte, Verifikation und technische Risiken.

Die Detaildokumente bleiben bewusst getrennt:

- [guide.md](guide.md): Setup, Betrieb und Troubleshooting,
- [mapping.md](mapping.md): Zuordnung des Fach-/Thesenkonzepts zum Code,
- [limitations.md](limitations.md): Grenzen des Demonstrators,
- [flow.mmd](flow.mmd): aus dem kompilierten Graphen erzeugter Ablauf.

## Kurzurteil zur Architektur

**Für einen Demonstrator mit zwei Prozessen ist die Architektur sinnvoll und
sollte nicht grundlegend ersetzt werden.** LangGraph bildet explizite
Verzweigungen und Human-in-the-loop-Unterbrechungen passend ab. Die Trennung
von deterministischer Governance und LLM-Aufruf ist fachlich wichtig, im Code
sichtbar und durch Tests geschützt. Prozessspezifische Module verhindern,
dass die beiden Abläufe unkontrolliert ineinander wachsen.

**Für Produktion oder deutlich mehr Prozesse ist sie in der heutigen Form
nicht geeignet.** Die wichtigsten Grenzen sind die synchrone Ausführung in
Streamlit, SQLite als gemeinsame Laufzeitdatenbank, die Nutzung des internen
Checkpoint-Schemas als Fallübersicht, fehlende echte Authentifizierung und
die teilweise Abweichung zwischen deklarierter Modellklasse und realem
LLM-Aufruf. Eine Migration sollte jedoch von konkreten Last-, Sicherheits-
oder Änderungsanforderungen ausgelöst werden, nicht vom Wunsch nach einer
abstrakteren Architektur.

### Was gut wartbar ist

- Der Kontrollfluss ist explizit in `graph/workflow.py` verdrahtet.
- Beide Prozesse teilen nur den Intake und haben danach eigene Agenten-,
  Node- und UI-Module.
- Persistierte HITL-Nachrichten sind als Verträge in `contracts.py` definiert.
- Agenten- und Prozessmetadaten sind in Registries zentralisiert.
- Governance ist deterministisch und darf keine höheren Schichten oder
  Modellclients importieren; Architekturtests erzwingen dies.
- Der gespeicherte Ablauf wird gegen den kompilierten Graphen getestet.

### Was Wartung erschwert

- „Agent“, „Modellklasse“ und „LLM-Aufruf“ bedeuten nicht dasselbe. Aktuell
  ruft nur die Klassifikation tatsächlich ein Modell auf; UI und Preflight
  behandeln trotzdem vier Rollen als modellnutzend.
- Ein neuer Prozess ist nur teilweise registry-getrieben und erfordert
  weiterhin Änderungen an Graph, Routing, UI-View, Übersetzungen und Tests.
- Fallzustand und Fallliste hängen am LangGraph-Checkpoint; es gibt keine
  eigene, migrationsfähige Fallprojektion.
- Node-Namen, Log-Schrittnamen und UI-Schritte sind getrennte Namensräume.
  Tests verhindern Drift, die Kopplung bleibt aber bei Änderungen relevant.
- Die Datenhaltung ist absichtlich prototypisch und nicht auf parallele
  Verarbeitung ausgelegt.

## Systemkontext

```text
 Einspeiser / Prüfer
         |
         +---------------------+
         |                     |
         v                     v
 Streamlit-UI               demo.py (CLI)
         |                     |
         +----------+----------+
                    v
        kompilierter LangGraph-Workflow
             |       |        |
             |       |        +----> Ollama oder Anthropic
             |       |              (aktuell nur Klassifikation)
             |       |
             |       +-------------> Navision-Mock / ELO-Mock (HTTP)
             |
             +---------------------> SQLite-Checkpoints
             +---------------------> SQLite-Stammdaten, Uploads, Audit,
                                      ERP-/DMS-Mockzustand
```

Der Prototyp automatisiert zwei Belegarten:

- Prozess A, Zahlungsbestätigung: Abgleich und nach menschlicher Freigabe
  Verbuchung in Navision.
- Prozess B, Eingangsrechnung: Kostenstellenzuordnung und Ablage in ELO;
  eine Kostenstellenfreigabe ist nur bei fehlender/ungültiger Referenz nötig.

Nicht im System enthalten sind reale Identität, reales AD/Entra, echte ERP-
oder DMS-Schnittstellen, ein Worker-/Queue-System und produktionsreife
unveränderliche Audit-Speicherung.

## Ausführbarer Workflow

Der folgende Block ist die technische Referenz des Kontrollflusses. Er wird
aus `build_graph().compile().get_graph().draw_mermaid()` erzeugt. Der Test
`tests/test_flow.py` vergleicht seine Kanten und [flow.mmd](flow.mmd) mit dem
kompilierten Graphen.

```mermaid
---
config:
  flowchart:
    curve: linear
---
graph TD;
	__start__([<p>__start__</p>]):::first
	reader(reader)
	klassifikation(klassifikation)
	abgleich(abgleich)
	buchung(buchung)
	klaerfall(klaerfall)
	kostenstelle(kostenstelle)
	freigabe_kostenstelle(freigabe_kostenstelle)
	elo(elo)
	__end__([<p>__end__</p>]):::last
	__start__ --> reader;
	abgleich -.-> buchung;
	abgleich -. &nbsp;hitl&nbsp; .-> klaerfall;
	buchung -. &nbsp;ende&nbsp; .-> __end__;
	buchung -. &nbsp;hitl&nbsp; .-> klaerfall;
	freigabe_kostenstelle -. &nbsp;ende&nbsp; .-> __end__;
	freigabe_kostenstelle -.-> elo;
	klaerfall -. &nbsp;ende&nbsp; .-> __end__;
	klaerfall -.-> buchung;
	klaerfall -.-> kostenstelle;
	klassifikation -. &nbsp;ende&nbsp; .-> __end__;
	klassifikation -. &nbsp;prozess_a&nbsp; .-> abgleich;
	klassifikation -. &nbsp;hitl&nbsp; .-> klaerfall;
	klassifikation -. &nbsp;prozess_b&nbsp; .-> kostenstelle;
	kostenstelle -.-> elo;
	kostenstelle -. &nbsp;freigabe&nbsp; .-> freigabe_kostenstelle;
	reader -. &nbsp;ende&nbsp; .-> __end__;
	reader -.-> klassifikation;
	elo --> __end__;
	classDef default fill:#f2f0ff,line-height:1.2
	classDef first fill-opacity:0
	classDef last fill:#bfb6fc
```

### Gemeinsamer Intake

1. UI oder CLI erzeugt eine `thread_id` und den initialen `Case`-State.
2. `reader` ruft `tools.reader.read_document()` auf. Die
   Berechtigungsprüfung liegt innerhalb des Tools und erfolgt vor jedem
   Dateizugriff.
3. Bei Ablehnung endet der Vorgang mit `zugriff_verweigert`; PDF-Parser,
   Modell und Zielsystem werden nicht aufgerufen.
4. Bei Erfolg wird das PDF deterministisch in Markdown umgewandelt und der
   SHA-256 des Rohdokuments berechnet.
5. `klassifikation` klassifiziert und extrahiert die Felder in einem
   Modellaufruf. Pydantic validiert die Antwort. Nach maximal zwei ungültigen
   Antworten wird eskaliert, nicht geraten.
6. `route_document_type()` routet deterministisch anhand des bereits
   extrahierten Dokumenttyps. Der Orchestrator führt keinen zweiten
   Modellaufruf aus.

### Prozess A: Zahlungsbestätigung

1. `abgleich` normalisiert die Rechnungsnummer und liest den Stammdatensatz
   per exaktem SQL-Lookup.
2. Unbekannte, bereits bezahlte oder betragsabweichende Vorgänge laufen in
   `klaerfall`; der Happy Path läuft zu `buchung`.
3. `buchung` prüft die Policy. Da der Agent als Human-in-the-loop
   konfiguriert ist, erzeugt auch der Happy Path zunächst einen
   Freigabebedarf.
4. `klaerfall` persistiert mit `interrupt()` einen `ApprovalRequest`. Ein
   berechtigter Mensch setzt den Graphen später mit `Command(resume=...)`
   fort oder verwirft ihn.
5. Nach Freigabe läuft `buchung` ein zweites Mal, prüft die Berechtigung des
   Prüfers erneut und ruft `POST /booking` am Navision-Mock auf.

Wichtig: Ein Logeintrag des Nodes `buchung` beweist noch keine Buchung. Der
erste Durchlauf fordert nur die Freigabe an. Das fachliche Ergebnis steht in
`state["outcome"]` und wird zusätzlich über `graph/effects.py` im Zielsystem
nachgelesen.

### Prozess B: Eingangsrechnung

1. `kostenstelle` löst die extrahierte Referenz exakt gegen den
   Kostenstellenkatalog auf; es gibt kein semantisches Matching.
2. Eine eindeutige Referenz läuft ohne Dialog direkt zu `elo`.
3. Eine fehlende oder unbekannte Referenz führt zu
   `freigabe_kostenstelle`. Der Prüfer wählt eine Kostenstelle und setzt den
   Graphen fort oder verwirft den Vorgang.
4. `elo` prüft die Write-Policy und ruft `POST /archive` am ELO-Mock auf.
   Die Dokumentidentität basiert auf dem SHA-256; erneute Ablage desselben
   Inhalts liefert dieselbe Archiv-ID.

Prozess B endet mit der Archivierung. Er schreibt nie nach Navision.

### Fehler- und Wiederaufnahmesemantik

- Modell nicht erreichbar: keine Wiederholung, Audit-Eintrag und Eskalation
  in den Freigabepfad.
- Modellschema verletzt: genau ein Korrekturversuch, danach Eskalation.
- Zielsystem nicht erreichbar/Antwort ungleich Erfolg: Vorgang endet als
  `abgelehnt` beziehungsweise `archivierung_fehlgeschlagen`.
- Mensch lehnt ab oder ist nicht berechtigt: Ende mit `verworfen`.
- Ein wartender Vorgang ist durch den Checkpoint, nicht durch den Browser,
  definiert. Ein anderer Tab kann ihn fortsetzen.
- Es existiert kein automatischer Retry für HTTP-Schreibaufrufe. ELO ist auf
  Dokumenthash-Ebene idempotent, Navision schützt gegen Doppelbuchungen über
  den Rechnungsstatus.

## Komponenten, Verantwortungen und Abhängigkeiten

| Bereich | Zentrale Dateien | Verantwortung | Darf kennen |
|---|---|---|---|
| Verträge/Konfiguration | `config.py`, `contracts.py`, `agent_registry.py`, `process_registry.py` | Einstellungen, persistierte Nachrichten, Agenten- und Prozessmetadaten | möglichst keine höheren Schichten |
| Governance | `governance/ad.py`, `policy.py`, `audit.py` | Identität/Gruppen, Write-/Approval-Regeln, Audit-Kette | Konfiguration und Agenten-Registry; nie LLM, Graph oder UI |
| Reader | `tools/reader.py` | autorisierter PDF-Zugriff, Parsing, Dokumenthash | Governance und Konfiguration |
| LLM | `llm/client.py`, `extraction.py`, `preflight.py`, `model_overrides.py` | Providerwahl, Transport, Schema-Validierung, Readiness | Agenten-Registry und Konfiguration |
| Domain | `agents/shared/`, `agents/payment_confirmation/`, `agents/incoming_invoice/` | fachliche Entscheidungen und Zielsystemaufrufe | Governance, LLM beziehungsweise Adapter |
| Orchestrierung | `graph/workflow.py`, `graph/nodes/`, `graph/state.py` | Nodes verdrahten, Status fortschreiben, HITL unterbrechen | Domain-Komponenten und Verträge |
| Projektionen | `graph/cases.py`, `graph/effects.py` | Fallliste/-status und Nachweis des Zielsystemeffekts | Checkpoint beziehungsweise Stammdaten-DB |
| Adapter | `mocks/navision.py`, `mocks/elo.py` | strikte simulierte Zielsysteme | DB und Audit |
| Präsentation | `ui/`, `demo.py` | Start/Fortsetzung, Anzeige, Übersetzung | Graph, Projektionen, Registries; keine Policy-Entscheidung nur im UI |

Die wichtigste erzwungene Grenze ist `governance/`: Eine
Berechtigungsentscheidung darf weder ein LLM noch eine von ihr kontrollierte
höhere Schicht erreichen. `tests/test_layer_boundaries.py` prüft Imports per
AST. `tests/test_process_separation.py` schützt zusätzlich die Trennung der
beiden Prozessmodule.

### Abhängigkeitsrichtung

```text
 config.py / contracts.py / agent_registry.py
                 ^
                 |
 governance/     |       process_registry.py
       ^         |               ^
       |         |               |
 tools/  llm/  agents/ <----- graph/nodes/
                          ^          ^
                          |          |
                       mocks/   graph/workflow.py
                                      ^
                                      |
                                 ui/ und demo.py
```

Das Bild ist vereinfacht: `process_registry.py` importiert den
`DocumentType` aus `agents/shared/schemas.py`, und die Prozess-B-View liest
den Kostenstellenkatalog über den Domain-Agenten nach. Diese pragmatischen
Kopplungen sind für den Prototyp vertretbar, sollten aber bei einer
Produktionsmigration durch neutrale Vertrags- beziehungsweise Query-Module
ersetzt werden.

## Agentenmodell versus reale LLM-Nutzung

`agent_registry.py` ist ein fachliches Rollen- und Risikomodell. Eine
`model_class` dort ist derzeit **kein Beweis für einen Modellaufruf**. Die
reale Call Chain lautet ausschließlich:

`agents/shared/classification.py` → `llm/extraction.py` →
`llm/client.py::client_for()` → Ollama oder Anthropic.

| Komponente | deklarierte Modellklasse | tatsächlicher LLM-Aufruf |
|---|---:|---:|
| Reader | kein Modell | nein |
| Orchestrator | lokal/klein | nein; deterministisches Routing |
| Klassifikation/Extraktion | vision-fähig | **ja**, aber aktuell nur mit Markdown, ohne Bildinput |
| Abgleich | kein Modell | nein; SQL-Lookup |
| Buchung | Frontier | nein; Policy + HTTP |
| Kostenstelle | kein Modell | nein; SQL-Lookup |
| ELO | lokal/klein | nein; Policy + HTTP |
| Policy/Audit | kein Modell | nein |

Das ist die wichtigste dokumentarische Abweichung im Projekt. Sie hat eine
operative Folge: `llm/preflight.py` und die Seite `ui/pages/models.py`
leiten Modellbedarf aus der Registry ab und verlangen beziehungsweise
konfigurieren dadurch auch Modelle für Rollen, die sie im aktuellen Code
nicht aufrufen. Bis dies im Code vereinheitlicht ist, gilt für Wartung:

- Laufzeitabhängigkeiten immer über die Call Chain bestimmen.
- Registry-Werte als Ziel-/Risikoklassifikation lesen.
- Änderungen an Modellklassen gegen Preflight, Modellseite und tatsächliche
  Aufrufer testen.

## Persistenz und Datenverantwortung

| Speicher | Inhalt | Besitzer/Zugriff | Lebenszyklus |
|---|---|---|---|
| `data/inbox/*.pdf` | hochgeladene und generierte Rohbelege | Intake schreibt, Reader liest, UI zeigt Vorschau | zur Laufzeit keine Bereinigung; der Demo-Generator setzt PDFs zurück |
| `data/masterdata.db` | Rechnungen, Kostenstellen, Lieferanten, AD-Mock, Uploads, Archiv-Mock, Audit | fast alle fachlichen Komponenten über kurze SQLite-Verbindungen | durch `data.generate` für Demo-Daten neu erzeugbar |
| `data/checkpoints.sqlite` | LangGraph-State und Interrupts pro `thread_id` | kompilierter Graph; `graph/cases.py` liest Thread-IDs direkt | Fall ist hier die Source of Truth |
| `data/model_overrides.json` | live gesetzte Provider-/Modellwahl | Modellseite und `llm/model_overrides.py` | sofort wirksam, ohne Neustart |
| `.env` | globale Konfiguration | `config.py` beim Import | Änderung erfordert Neustart |

### Fall, Upload und Dokument sind verschiedene Identitäten

- `upload_id` bezeichnet die Annahme einer Datei.
- `content_hash` bezeichnet ihren Inhalt.
- `case_id`/LangGraph-`thread_id` bezeichnet genau einen Verarbeitungslauf.
- `filename` ist nur Anzeige-/Quellinformation und nicht eindeutig.

Ein Upload kann mehrere Cases erzeugen. Der Case selbst wird absichtlich
nicht in `masterdata.db` dupliziert, sondern ausschließlich aus dem
Checkpoint gelesen. Die Fallübersicht scannt dafür alle Thread-IDs und ruft
pro Thread `app.get_state()` auf; das ist für wenige Demo-Fälle akzeptabel,
aber keine skalierbare Query-Schnittstelle.

### Transaktionsgrenzen

- Agenten öffnen überwiegend pro Schritt eine neue SQLite-Verbindung.
- Audit-Helper committen nicht selbst; der Aufrufer legt die
  Transaktionsgrenze fest.
- HTTP-Zielsysteme besitzen in der Demo dieselbe SQLite-Datei, sind aber
  logisch externe Systeme. Ein Commit über Anwendung und HTTP-Adapter hinweg
  ist nicht atomar.
- Der Checkpoint und `masterdata.db` sind zwei getrennte Transaktionsräume.
  Ein Zielsystemeffekt kann daher nicht gemeinsam mit dem Graph-State
  committed werden.

Bei Produktionsbetrieb wären Outbox/Inbox, idempotente Kommandos und eine
explizite Recovery-Strategie nötig.

## Persistierte Verträge und Sources of Truth

| Konzept | Source of Truth | Konsumenten | Änderungshinweis |
|---|---|---|---|
| Agentenrolle, Autonomie, Oversight, Schreibrecht | `agent_registry.py` | Policy, Architektur-/Modellseite, Preflight | kann Laufzeit-Policy ändern |
| Prozessmetadaten und UI-Schritte | `process_registry.py` | Navigation, Listen, Stepper, Approval-Auflösung | Node-/Log-Namen mitprüfen |
| Graphknoten und Routinglabels | `graph/workflow.py`, `graph/nodes/*` | LangGraph | `flow.mmd` und Architekturblock regenerieren |
| Case-State | `graph/state.py` | Nodes, Checkpointer, UI, CLI | `TypedDict` validiert Laufzeitdaten nicht |
| Interrupt/Resume/Outcome | `contracts.py` | Nodes, Checkpoint, UI, CLI | rückwärtskompatibel halten; pausierte Cases überleben Deployments |
| DB-Schema | `data/schema.sql` | Generator, Agents, Mocks, UI | keine allgemeine Migration vorhanden |
| UI-Übersetzung | `ui/locales/*.json`, deutsche Registry-Texte | UI | aufgezeichnete Evidenz wird nicht übersetzt |

### Drei verschiedene „Outcome“-Begriffe

| Begriff | Bedeutung | Beispiele |
|---|---|---|
| `governance.policy.Outcome` | Ergebnis genau einer Policy-Prüfung | `erlaubt`, `freigabe_noetig`, `verweigert` |
| `contracts.CaseOutcome` | Endzustand des gesamten Cases | `verbucht`, `archiviert`, `verworfen` |
| Audit-Spalte `outcome` | Ergebnis eines einzelnen Audit-Ereignisses; offenes Vokabular | Policy-, Agenten-, Freigabe- oder Case-Wert |

Die Begriffe dürfen nicht zusammengeführt werden: Sie beantworten
unterschiedliche Fragen und haben unterschiedliche Konsumenten.

## Sicherheits- und Governance-Modell

1. Reader-Zugriff erfordert `SG-CHG-DocIngest` und wird vor Dateizugriff im
   Tool geprüft.
2. Schreibaktionen fragen `governance.policy.check_write_action()` direkt am
   Write-Site.
3. Freigaben erfordern `SG-CHG-Freigabe`; der Resume-Payload wird nicht als
   vertrauenswürdig behandelt.
4. Unbekannte Nutzer und nicht abgedeckte Oversight-Modi enden mit Deny.
5. Der Audit-Trail verkettet alle Einträge per Hash; DB-Trigger verhindern
   UPDATE/DELETE durch normale SQL-Nutzung.
6. Zielsystem-Mocks prüfen eigene Vorbedingungen, statt dem aufrufenden
   Agenten blind zu vertrauen.

Bewusste Grenzen: Die Anmeldung ist eine Auswahlbox, nicht Authentifizierung.
Die Zugehörigkeit zur Freigabegruppe wird erzwungen, aber Einspeiser und
Prüfer dürfen dieselbe Person sein. Wer direkten Schreibzugriff auf die
SQLite-Datei hat, kann die gesamte Audit-Kette neu aufbauen. Siehe
[limitations.md](limitations.md).

## Wartungslandkarte

### Einen vorhandenen Prozess ändern

1. Fachlogik in `agents/<prozess>/` ändern.
2. State-Schreibzugriffe in `graph/nodes/<prozess>.py` und `graph/state.py`
   abgleichen.
3. Routing in `graph/workflow.py` prüfen.
4. Prozessmetadaten, Stepper und Ergebnisdarstellung in
   `process_registry.py` und `ui/cases/process_views/<prozess>.py` prüfen.
5. Verträge nur über `contracts.py` ändern.
6. Prozess-, Flow-, Contract- und Szenariotests ausführen.

### Einen dritten Prozess hinzufügen

Ein Registry-Eintrag allein genügt nicht. Mindestens erforderlich sind:

1. `DocumentType` und Extraktionsschema erweitern.
2. `process_registry.py` ergänzen.
3. Agenten unter `agents/<prozess>/` anlegen.
4. Nodes unter `graph/nodes/<prozess>.py` anlegen.
5. Nodes und Kanten in `graph/workflow.py` verdrahten.
6. Routing in `graph/nodes/shared.py::route_document_type()` erweitern.
7. View-Fragment und `VIEWS`-Eintrag unter `ui/cases/process_views/`
   ergänzen.
8. Bei Sonderlogik den Stepper in `ui/cases/steps.py` erweitern.
9. Sprachkataloge und Tests aktualisieren.
10. [flow.mmd](flow.mmd) und den eingebetteten Graphen regenerieren.

Ab drei bis vier fachlich unabhängigen Prozessen sollte geprüft werden, ob
ein gemeinsamer Intake-Subgraph plus ein separat kompilierter Graph pro
Prozess verständlicher ist als der weiter wachsende gemeinsame Graph.

### Einen persistierten HITL-Vertrag ändern

- Felder in `ApprovalRequest`/`ApprovalResponse` ergänzen, nicht als freie
  Dict-Schlüssel in UI und Nodes verteilen.
- Neue Felder optional und mit sicherem Default lesen.
- Alte Checkpoints ohne das neue Feld testen.
- Enum-Werte nicht umbenennen, solange wartende Cases existieren.
- CLI und UI gemeinsam anpassen; beide produzieren Resume-Payloads.

### Das Datenbankschema ändern

- `data/schema.sql`, `data/generate.py`, Query-Code und Fixtures gemeinsam
  anpassen.
- Für Demo-Daten ist Neuaufbau erlaubt; für reale Daten existiert keine
  Migrationsstrategie.
- Audit-Felder sind Teil des Hashmaterials. Eine Änderung erfordert eine
  versionierte neue Kette und Verankerung des alten Head-Hash, nicht das
  nachträgliche Umhashen bestehender Einträge.

### Ein reales Zielsystem anbinden

Die HTTP-Aufrufe liegen derzeit direkt in den Domain-Agenten. Für eine reale
Integration zuerst ein Adapterinterface einführen und danach Mock und
Produktivadapter dahinter legen. Zusätzlich festlegen:

- Authentifizierung und Secret-Handling,
- Timeouts, Retry- und Backoff-Regeln,
- idempotenter Schlüssel pro Case/Aktion,
- Fehlerklassifikation (fachlich, transient, permanent),
- Observability sowie Outbox/Recovery.

### Modell oder Provider ändern

- Globale Defaults: `.env`/`config.py`; Neustart nötig.
- Laufzeit-Override: `data/model_overrides.json`; sofort wirksam.
- Schema-/Retry-Verhalten: `llm/extraction.py`.
- Tatsächlichen Aufrufer per `rg 'client_for\(|extract\('` verifizieren;
  nicht allein auf `model_class` vertrauen.

## Test- und Verifikationsstrategie

Die Tests prüfen überwiegend deterministische Architekturregeln; reale
Modellqualität wird nicht gemessen.

| Risiko | Relevante Tests |
|---|---|
| Graph/Dokumentationsdrift | `tests/test_flow.py` |
| Governance erreicht LLM/höhere Schicht | `tests/test_layer_boundaries.py` |
| Prozess A/B koppeln sich | `tests/test_process_separation.py` |
| Persistierte Payloads driften | `tests/test_contracts.py` |
| Audit-Manipulation | `tests/test_audit.py` |
| Policy-/Freigaberegeln | `tests/test_policy.py`, `tests/test_scenarios.py` |
| Upload → Case → Audit | `tests/test_upload_to_case.py` |
| Modellwahl/Validierung | `tests/test_llm.py`, `tests/test_preflight.py` |
| UI-Struktur und Sprache | `tests/test_ui_smoke.py`, `tests/test_i18n.py`, `tests/test_ui_language.py` |

Minimal nach einer Architekturänderung:

```bash
.venv/bin/python -m pytest -q \
  tests/test_flow.py \
  tests/test_layer_boundaries.py \
  tests/test_process_separation.py \
  tests/test_contracts.py \
  tests/test_structure.py
```

Vor Übergabe die vollständige Suite:

```bash
.venv/bin/python -m pytest -q
```

## Technische Risiken und empfohlene Reihenfolge

| Priorität | Risiko | Auswirkung | Empfohlene Maßnahme |
|---|---|---|---|
| hoch | Registry/Preflight behaupten LLM-Nutzung für Orchestrator, Buchung und ELO, die nicht stattfindet | unnötige Modellvoraussetzungen und irreführende Bedienung/Doku | getrennte Felder für Risikoklasse und `invokes_model` oder reale Aufrufer als Source of Truth verwenden |
| hoch | Unterschiedlicher Inhalt mit gleichem Dateinamen überschreibt in `data/inbox` die ältere Datei | alter Upload/Case kann auf veränderten Rohbeleg zeigen | immutable Ablage unter `upload_id` oder Content-Hash; Originalname nur als Metadatum |
| hoch vor Produktion | SQLite + globale Audit-Hashkette + synchrone Läufe | Locks/Races und geringe Parallelität | Worker-Queue, transaktionale DB, serialisierter Audit-Writer |
| hoch vor Produktion | Mock-Login und unvollständiges Vier-Augen-Prinzip | Identität und Funktionstrennung nicht belastbar | OIDC/Entra, serverseitige Claims, `approver != submitter` in Policy |
| mittel | Cases werden über internes Checkpoint-Schema aufgelistet | O(n)-Zugriff und Kopplung an LangGraph-SQLite-Schema | eigene Fallprojektion/Event-Consumer mit stabiler Query-API |
| mittel | keine Versionierung von State, Checkpoints und Audit-Schema | Deployments können wartende Cases unlesbar machen | Schema-/Contract-Versionen und Migrations-/Drain-Strategie |
| mittel | direkte synchrone HTTP-Aufrufe ohne Retry/Outbox | unklare Recovery nach Teilfehlern | Adapter, Idempotency-Key, Retry-Klassen, Outbox |
| mittel | `Case` ist ein `TypedDict` ohne Runtime-Validierung | fehlende/inkonsistente Felder werden spät sichtbar | validierte Boundary-Modelle oder Node-Ein-/Ausgabeverträge |
| niedrig im Prototyp | manuell gepflegte Sonderfälle im Stepper | neuer Prozess kann falsch angezeigt werden | Schrittstatus als Prozessmetadaten/State-Machine modellieren |

### Wann die Architektur neu bewertet werden sollte

Eine strukturelle Weiterentwicklung ist fällig, sobald mindestens eines
dieser Kriterien gilt:

- parallele Verarbeitung oder mehrere produktive Nutzer,
- reale, nicht idempotente Zielsysteme,
- verbindliche regulatorische Audit-Anforderungen,
- Deployment mit wartenden Vorgängen über mehrere Codeversionen,
- mehr als drei bis vier eigenständige Prozesse,
- Such-/Reporting-Anforderungen über viele Cases,
- echte OCR-/Scan-Verarbeitung mit empirisch messbarer Modellqualität.

Bis dahin ist die beste Maintenance-Strategie: den expliziten Graphen und
die Prozessmodule beibehalten, die beschriebenen Abweichungen beseitigen und
Architekturregeln weiterhin als Tests statt nur als Prosa sichern.

## Empfohlene Lesereihenfolge für neue Maintainer

1. `README.md` und [guide.md](guide.md) für Zweck und Start.
2. `process_registry.py` und `agent_registry.py` für fachliche Struktur.
3. `graph/workflow.py` für den realen Kontrollfluss.
4. `graph/state.py` und `contracts.py` für persistierte Daten.
5. `graph/nodes/shared.py`, danach genau eines der Prozessmodule.
6. Die zugehörigen Agenten und Governance-Prüfungen.
7. `data/schema.sql` für Datenbesitz und Zielsystemeffekte.
8. `ui/cases/detail.py` und die passende `process_views`-Datei.
9. Die Architekturtests und [limitations.md](limitations.md).
