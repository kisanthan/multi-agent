# Grenzen des Prototyps

Der Prototyp ist ein **Demonstrations- und Machbarkeitsartefakt** (Design
Science Research nach Hevner et al. 2004), nicht produktionsreif. Diese
Grenzen gehören in den Fallbeispiel-Text (Kap. 6) und in die Limitationen der
Arbeit.

## Was der Prototyp belegt — und was nicht

**Belegt:** die *Architektur* ist machbar. Rollen-/risikobasierte
Agentenkonfiguration, Human-in-the-loop an Risikostellen, Least Privilege,
manipulationsgeschützter Audit-Trail und deterministische Governance außerhalb
des Sprachmodells laufen zusammen in einem lauffähigen System.

**Nicht belegt:** die *Extraktionsgüte* auf Echtdaten. Alle Dokumente sind
synthetisch, nativ erzeugt (nicht gescannt) und strukturell sauber. Reale
Eingangsrechnungen sind heterogener (Scans, Fremdsprachen, uneinheitliche
Layouts, OCR-Fehler). Der Prototyp sagt nichts über die Trefferquote der
Klassifikation/Extraktion unter realen Bedingungen aus. Diese Unterscheidung
ist zentral und sollte in Kap. 6 klar benannt werden.

## Konkrete Limitationen

### L1 — Synthetische Daten
Seed-fest generiert (`data/generate.py`). Störfälle (unbekannte Nummer,
Dublette, unplausibler Betrag, mehrdeutige Kostenstelle, unberechtigter
Einspeiser) sind bewusst konstruiert, nicht empirisch beobachtet. Die
Kostenstellen-Zuordnungsregeln sind vereinfachte Schlüsselwortlisten.

### L2 — Schema-Adhärenz lokaler Modelle (Risiko R1)
Lokale Modelle halten ein übergebenes JSON-Schema nicht zuverlässig ein; für
Ollama ist das ein offener, dokumentierter Bug
([ollama/ollama#15540](https://github.com/ollama/ollama/issues/15540), Stand
April 2026), betreffend u. a. Gemma 4 26B und Qwen 3 9B.

Der Prototyp behandelt das **nicht als behobenes Problem, sondern als
abgefangenes**: `llm/extraktion.py` validiert jede Modellantwort gegen das
Pydantic-Schema, fasst bei Verletzung genau einmal mit dem konkreten Fehler
nach und eskaliert dann in die HITL-Queue statt zu raten. Ein Modellfehler wird
so zum Freigabefall, nicht zum stillen Datenfehler. Das ist selbst ein
Architekturargument der Arbeit — aber es bleibt eine Kompensation, keine
Garantie für Modellqualität.

### L3 — Gemockte Zielsysteme
Navision (Dynamics NAV) und ELO sind FastAPI-Mocks. Sie bilden die Schnittstellen
plausibel nach (inkl. Vorbedingungsprüfung und Ablehnung), aber nicht die
Fachlogik, Performance oder Fehlermodi der Echtsysteme. Die AD-/Entra-Anbindung
ist eine SQLite-Tabelle, kein echtes Verzeichnis; es gibt keine echte
Authentifizierung — der „angemeldete Nutzer" ist im Prototyp eine Auswahl.

### L3b — Kostenstellenreferenz als Betriebsannahme
Der Kostenstellen-Agent ist ein exakter referenzieller Nachschlag (Thesis §7.4):
Er setzt voraus, dass der Beleg eine maschinenlesbare Kostenstellenreferenz trägt
(im Prototyp ein Code `KTR-…`, den der Extraktions-Agent liest). Reale
Eingangsrechnungen tragen eine solche Referenz nicht immer explizit — dann greift
korrekterweise der Klärfall (menschliche Zuordnung) häufiger. Der Prototyp
demonstriert den deterministischen Pfad; die Häufigkeit des Klärfalls auf
Echtbelegen ist empirisch offen.

### L4 — Governance-Umfang
Die Policy-Engine deckt die im Fachkonzept genannten Regeln ab (RBAC,
Autonomiestufen, Betragsschwellen, Vier-Augen-Prinzip). Sie ist kein
vollständiges ABAC-/Zero-Trust-System; Just-in-Time-Rechtevergabe und Zero
Standing Privilege sind konzeptionell vorgesehen, aber nicht implementiert.

### L5 — Audit-Trail-Schutz
Die Hash-Verkettung erkennt nachträgliche Manipulation zuverlässig
(`verify_chain()`), und DB-Trigger verhindern UPDATE/DELETE über die Anwendung.
Ein Angreifer mit direktem Schreibzugriff auf die SQLite-Datei könnte die Kette
zwar nicht unbemerkt *fälschen*, aber die gesamte Tabelle *neu aufbauen*. Echte
Manipulationssicherheit erforderte externe Verankerung (z. B. periodisches
Veröffentlichen des Kopf-Hashes, WORM-Speicher). Für ein Demonstrationsartefakt
ist die Verkettung ausreichend und der Nachweis erbracht.

### L6 — Keine Nebenläufigkeit / kein Mehrbenutzerbetrieb
SQLite im WAL-Modus, ein Vorgang zur Zeit gedacht. Parallele Läufe gegen
dieselbe DB sind nicht abgesichert.

### L7 — Modellversionen und -preise
Alle Modell-IDs (`claude-opus-4-8`, `claude-haiku-4-5`, `qwen3:8b`,
`llama3.2-vision:11b`) und Preise sind mit Abrufdatum **17.07.2026** zu
verstehen und wechseln quartalsweise.

## Umgebungsbedingte Hinweise (dieser Rechner)

- Läuft auf Python 3.14; alle Dependencies haben native Wheels. `uv` ließ sich
  wegen defekter Homebrew-Rechte nicht installieren — venv + gepinnte
  `requirements.txt` erfüllen die Reproduzierbarkeit gleichwertig.
- Der Faker-Import ist auf diesem (stark gefüllten) Dateisystem ungewöhnlich
  langsam (~40 s). Deshalb importieren nur `data/generate.py` Faker; Demo und
  Tests nutzen die Pfade aus `config.py` und bleiben schnell. Testdaten werden
  einmal per `python -m data.generate` erzeugt.
