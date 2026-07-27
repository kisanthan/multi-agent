# Architektur des Prototyps

## Überblick

Der Prototyp realisiert ein Multiagentensystem für zwei interne Finanzprozesse
der CHG-MERIDIAN. Beide Prozesse laufen durch **einen gemeinsamen
LangGraph-Graphen** mit geteilten Komponenten (Reader, Orchestrator,
Klassifikation, Datenbasis). Die Verarbeitung ist in Schichten getrennt, deren
Grenzen im Code erzwungen sind.

```
Eingang (PDF + Einspeiser-UPN)
        │
        ▼
   [Reader-Tool]  ── AD-Check (Least Privilege) ──► verweigert → Ende + Audit
        │  PDF → Markdown (deterministisch, kein KI-Agent)
        ▼
   [Klassifikation & Extraktion]  ── LLM, validiert, R1-Eskalation
        │
        ▼
   [Orchestrator]  ── Conditional Edge nach Dokumenttyp
        ├──────────────► Prozess A                 └──────────────► Prozess B
        │  [Abgleich] (Stufe 1, deterministisch)      [Kostenstelle] (Stufe 2, LLM)
        │      │ Nummer vorhanden?                        │ Zuordnung eindeutig?
        │      │   nein → Klärfall (HITL)                 │   nein → Klärfall/Freigabe (HITL)
        │      ▼                                           ▼
        │  [Buchung] (Stufe 3)                        [ELO] (Stufe 3)
        │      │ > Schwelle? → HITL                        │
        │      ▼                                           ▼
        │   Navision /booking (offen→bezahlt)         ELO /archive  ── Prozessende
        │
        ▼
   Querschnitt: [Policy] (deterministisch) · [Audit] (hash-verkettet, read-only)
```

> **Prozess B endet bei ELO** (Diagramm Teil 3): revisionssichere Archivierung
> ist das Prozessende, es gibt keine Navision-Verbuchung in Prozess B. Navision
> wird nur in Prozess A angesprochen. Beide Domänen-Agenten (Kostenstelle, ELO)
> sind Human-on-the-loop — die Vier-Augen-Freigabe greift nur bei mehrdeutiger
> Kostenstellen-Zuordnung.

## Schichten und ihre Grenzen

| Schicht | Verzeichnis | LLM? | Grenze |
|---|---|---|---|
| Konfiguration | `registry.py`, `config.py` | nein | von Governance gelesen |
| Governance | `governance/` | **nein, erzwungen** | importiert keine höhere Schicht, keinen LLM |
| Werkzeuge | `tools/`, `llm/` | LLM gekapselt | AD-Check als Eintrittsbedingung |
| Agenten | `agents/` | teils | rufen Governance + LLM + Mocks |
| Orchestrierung | `graph/` | nein | verdrahtet Agenten, setzt HITL-Interrupts |
| Zielsysteme | `mocks/` | nein | prüfen eigene Vorbedingungen |

Die wichtigste Grenze ist die der **Governance-Schicht**: `governance/policy.py`,
`ad.py` und `audit.py` importieren keinen LLM-Client und nichts aus `agents/`.
Das ist kein Stilprinzip, sondern die zentrale technische Aussage der Arbeit und
per AST-Test erzwungen (`tests/test_schichtgrenze.py`). Der praktische Beleg:
jede Governance-Entscheidung ist deterministisch und mit einem Unit-Test
reproduzierbar — bei einem Sprachmodell wäre sie das nicht.

## Warum LangGraph

Der graphbasierte Ansatz mit explizitem Zustand und Checkpointer bildet drei
Anforderungen der Arbeit direkt ab:

- **Human-in-the-loop:** `interrupt()` hält den Vorgang an einer Risikostelle
  an; der Checkpointer persistiert den Zustand, ein Mensch setzt ihn später über
  `Command(resume=...)` fort. Ohne Checkpointer kein HITL — der Checkpointer ist
  daher nicht optional (`graph/workflow.py::kompiliere`).
- **Risikobasierte Freigabepunkte:** als Conditional Edges modelliert, deren
  Bedingung aus der Policy stammt (Betragsschwelle) oder aus dem Aufsichtsmodus
  der Registry (Vier-Augen-Prinzip).
- **Audit-Trail:** jeder Knoten schreibt hash-verkettet in den Trail; der
  Graphzustand führt ein Laufprotokoll für UI und CLI.

Stack-Validierung (Stand 17.07.2026): LangGraph 1.2.9 bestätigt; PyMuPDF4LLM
statt Docling als Default, weil die synthetischen PDFs nativ sind und Docling
1–2 GB Modellgewichte für keinen Mehrwert lüde (Docling bleibt per
`READER_PARSER=docling` wählbar). Details in [mapping.md](mapping.md).

## Modell-Bereitstellung

Die Modellwahl ergibt sich aus zwei Angaben: der **Risikoklasse** eines Agenten
(`registry.py`, `Modellklasse`) und dem **Bereitstellungsmodus** (`.env`,
`MODELL_MODUS`). `llm/client.py::waehle_modell` kombiniert beide:

| Modus | lesende/unkritische Rollen | risikobehaftete Rollen |
|---|---|---|
| `lokal` | Ollama | Ollama |
| `hybrid` | Ollama (Datenhoheit) | Anthropic (Frontier) |
| `cloud` | Anthropic | Anthropic |

Kein Agent kennt seinen Anbieter — das ist der Punkt der Abstraktion und die
technische Grundlage für Unterfrage 2 der Arbeit (Cloud vs. Open-Source je
Risikoklasse). Der Prototyp lädt selbst keine Modelle; er verbindet sich gegen
eine Ollama-Instanz (`OLLAMA_BASE_URL`), deren Modelle außerhalb bereitgestellt
werden. `demo.py --check` prüft die Bereitstellung.

## Datenfluss und Persistenz

Eine gemeinsame SQLite-Datenbank (`data/stammdaten.db`) hält Stammdaten,
AD-Mock, Zielsystem-Zustand und den Audit-Trail — bewusst eine Datei, weil die
Arbeit mit einer *gemeinsamen* Datenbasis argumentiert. Der
LangGraph-Checkpointer nutzt eine separate Datei (`data/checkpoints.sqlite`).

## Modell-IDs (Stand 17.07.2026, wechseln quartalsweise)

| Rolle | lokal (Ollama) | Cloud (Anthropic) | Cloud-Preis (In/Out je 1M) |
|---|---|---|---|
| lesend/klein | `qwen3:8b` | `claude-haiku-4-5` | $1 / $5 |
| Klassifikation (vision) | `llama3.2-vision:11b` | `claude-opus-4-8` | $5 / $25 |
| kritisches Schreiben | — | `claude-opus-4-8` | $5 / $25 |
