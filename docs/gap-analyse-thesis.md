# Gap-Analyse: Prototyp ↔ Thesis Abschnitt 6.4

Abgleich der praktischen Umsetzung gegen den Fließtext in `Masterarbeit.docx`,
Abschnitt **6.4 „Anwendung und Analyse der Prozessdomänen"** und die
Evaluationstabelle (7.2, Tabelle 10). Stand: 21.07.2026.

Legende: ✅ deckungsgleich · ⚠️ Divergenz/Klärungsbedarf · ➕ im Prototyp
zusätzlich (nicht in der Thesis).

---

## Deckungsgleich (kein Handlungsbedarf)

| Thesis 6.4 | Prototyp | |
|---|---|---|
| Zwei Prozesse A (Zahlungseingang) / B (Eingangsrechnung), gemeinsame Ingestionsstrecke | ein gemeinsamer Graph, geteilter Reader/Orchestrator/Datenbasis | ✅ |
| Fachliche Bearbeitung nur durch **Shared Domain Agents** | Registry: alle fachlichen Agenten Shared Domain | ✅ |
| Klassifikations-/Extraktions-Agent bestimmt Typ + liest Felder | `agents/klassifikation.py` (Typ + Felder in einem Durchgang) | ✅ |
| Orchestrator „ohne eigene fachliche Vollrechte", nur Weiterleitung | Routing-Funktion, kein Schreibrecht | ✅ |
| Reader-Tool **kein KI-Agent**, PDF→Markdown deterministisch | `tools/reader.py`, kein LLM | ✅ |
| **Prozess B: eindeutig → direkt ELO; sonst Klärfall (Vier-Augen, HITL)** | `route_kostenstelle` + `freigabe_kostenstelle` | ✅ |
| **Prozess B endet bei ELO** (revisionssichere Archivierung) | `elo → END`, keine Navision-Buchung in B | ✅ |
| Prozess A: Abgleich → Buchung setzt in Navision offen→bezahlt | `agents/buchung.py` → Navision-Mock `/booking` | ✅ |
| AD-Sicherheitsgruppe am Prozesseingang (Least Privilege) | AD-Check *innerhalb* `lies_dokument()` | ✅ |
| Policy prüft „deterministisch außerhalb des Sprachmodells" | `governance/policy.py`, per AST-Test erzwungen | ✅ |
| Audit „manipulationsgeschützt" | hash-verketteter Trail, append-only | ✅ |
| Modellunabhängige Abstraktionsschicht (5.1.5), Agent/Modell austauschbar | `llm/client.py::waehle_modell` | ✅ |
| Personal Agents treten nicht auf | keine im System | ✅ |

Der Prozess-B-Umbau dieser Session hat den Prototyp **exakt auf den Thesis-Text
gebracht**: eindeutige Zuordnung → direkt ELO, sonst Klärfall; ELO als
Prozessende.

---

## Divergenzen / Klärungsbedarf

### G1 — RAG: meine frühere Auskunft war falsch ⚠️ *(behoben in Doku)*

Die Thesis (6.4) entscheidet die RAG-Frage **bereits und eindeutig**: die
gemeinsame Datenbasis ist „bewusst nicht als semantisches Retrieval-System …
ausgeführt"; **beide** Nachschläge (Abgleich A *und* Kostenstellenzuordnung B)
gelten als „exakte, referenzielle Nachschläge auf strukturierte Stammdaten". RAG
ist nur komplementär vorgesehen — für den Extraktions-Agenten bei schwierigen
Layouts und zur Anreicherung der Klärfallprüfung.

→ Damit ist die Frage „RAG einbauen?" aus Thesis-Sicht **beantwortet: nicht in
die Datenbasis.** Meine frühere Einschätzung (RAG passe für die
Kostenstellen-Zuordnung) widersprach der Arbeit; `docs/mapping.md` I7 ist
korrigiert. Falls RAG überhaupt gebaut wird, dann dort, wo die Thesis es verortet
(Extraktions-Unterstützung / Klärfall-Anreicherung), nicht am Stammdatenabgleich.

### G2 — Kostenstellen-Agent: Thesis „exakter Nachschlag" vs. Prototyp „semantisch" ⚠️

Die Thesis beschreibt die Kostenstellenzuordnung als **exakten referenziellen
Nachschlag** (deterministisch). Der Prototyp implementiert sie **LLM-/schlüssel­
wortbasiert-semantisch** (`agents/kostenstelle.py`, Docstring: „eine semantische
Aufgabe, die sich nicht als exakte Abfrage formulieren lässt").

Das ist ein echter Widerspruch. Zwei Wege:

- **(a) Prototyp an Thesis angleichen:** Kostenstelle als deterministischen
  Nachschlag über eine explizite **Kostenstellen-Referenz** auf dem Beleg
  umsetzen (der Extraktions-Agent liest die Referenz, der Kostenstellen-Agent
  schlägt sie exakt nach). Damit würde der Agent — wie der Abgleich-Agent (I1) —
  ohne eigenes Sprachmodell arbeiten; „Mehrdeutigkeit" = Referenz fehlt/uneindeutig.
- **(b) Thesis-Text präzisieren:** Der eigene Prozessschritt „Zuordnung
  eindeutig?" mit Klärfall-Pfad zeigt, dass die Zuordnung einen
  **Klassifikationscharakter** hat — ein exakter Nachschlag ist nie „mehrdeutig".
  Die Formulierung „exakter referenzieller Nachschlag" trägt für die Kostenstelle
  also weniger weit als für die Rechnungsnummer. Ein, zwei Sätze in 6.4 würden das
  auflösen (z. B.: Kostenstellenzuordnung = referenzgestützt, aber mit
  Klassifikationsanteil bei fehlender/uneindeutiger Referenz).

**Empfehlung:** (b) — der Prototyp bildet die Realität (Zuordnung ist ein
Urteils-/Klassifikationsschritt) sauber ab, und die Existenz des Klärfall-Pfads
gibt dir das Argument. Falls die Betreuung strikte Determinismus-Kohärenz
verlangt, ist (a) der Weg; sag Bescheid, dann baue ich es um.

### G3 — Buchungs-Agent: Aufsichtsmodus widersprüchlich ⚠️

Hier ist die **Thesis selbst uneinheitlich**:

- **Thesis-Text** (Charakterisierungs-Absatz + Tabelle 10, Zeile
  Kontrollierbarkeit A): Buchungs-Agent „unter **Human-in-the-loop**"
  (finanzwirksames Schreibrecht).
- **Thesis-Abbildung 5** (`teil3_multiagentensystem.png`): Buchungs-Agent-Kachel
  beschriftet mit **Human-on-the-loop**; die HITL-Stelle ist die „Klärfall-Prüfung"
  (nur bei fehlender Nummer).
- **Prototyp:** `HUMAN_ON_THE_LOOP` als Default + **Betragsschwelle**
  (`BUCHUNG_SCHWELLE_EUR`: darunter automatisch, darüber HITL) — ein Konstrukt,
  das in der Thesis **gar nicht vorkommt** (➕).

→ **Zwei Dinge zu entscheiden:**
1. Text vs. Abbildung in der Arbeit angleichen (Buchungs-Agent: in-the-loop
   *oder* on-the-loop — durchgängig).
2. Prototyp danach ausrichten. Wenn die Arbeit **Human-in-the-loop** wählt
   (wie der Text nahelegt, finanzwirksam), sollte der Buchungs-Agent **immer**
   eine Freigabe verlangen; die Betragsschwelle entfiele oder würde als bewusste
   Prototyp-Erweiterung deklariert. Wenn **Human-on-the-loop** (wie die
   Abbildung), passt der Prototyp bereits, aber die Schwelle bleibt Prototyp-Zusatz.

**Empfehlung:** In der Arbeit für den finanzwirksamen Buchungsschritt
**Human-in-the-loop** wählen (konsistent mit „steigende Autonomie → engere
Aufsicht"), Abbildung 5 entsprechend anpassen, und im Prototyp die Schwelle als
optionale, dokumentierte Erweiterung behalten oder auf reines HITL umstellen.

### G4 — Dynamische Cloud-Eskalation der Extraktion fehlt ⚠️ *(klein)*

Thesis: Extraktion „vorrangig on-premise … nur bei **schwierigen Layouts** in die
Cloud eskalieren" — also eine *dynamische* Eskalation. Prototyp: **statische**
Modellzuordnung (Klassifikations-Agent = Vision-Klasse → im Hybrid-Modus immer
Cloud). Der beschriebene „on-prem zuerst, bei Schwierigkeit eskalieren"-Mechanismus
ist nicht umgesetzt.

→ Optional nachrüstbar: lokales VLM zuerst, bei niedrigem Konfidenz-/
Validierungssignal (R1-Retry greift schon!) auf Cloud eskalieren. Der
Eskalationspfad ist über die bestehende Validierungsschicht (`llm/extraktion.py`)
gut andockbar. Für die Kern-Demo nicht nötig, aber es würde Unterfrage 2 stärker
*vorführbar* machen.

### G5 — Audit-Felder nicht 1:1 wie im Text benannt ⚠️ *(klein)*

Thesis nennt als zu protokollierende Felder explizit: **Auftraggeber, Agent,
Datenquelle, Werkzeugaufruf, Policy-Entscheidung, Ergebnis**. Prototyp-Audit-
Spalten: `akteur` (=Auftraggeber ✅), `agent` ✅, `aktion` (~Werkzeugaufruf),
`entscheidung` (=Policy-Entscheidung ✅), `begruendung`, `payload` (enthält
Datenquelle/Datei + Ergebnis).

→ „Datenquelle" und „Ergebnis" stecken im `payload`, nicht als eigene Spalten.
Funktional vollständig, aber für einen **1:1-Nachweis gegen den Thesis-Wortlaut**
(Kriterium „Nachvollziehbarkeit", Tabelle 10) wäre es sauberer, sie als explizite
Felder zu führen. Kleiner Eingriff in `governance/audit.py` + Schema.

---

## Fazit

Der Prototyp deckt den Thesis-Abschnitt 6.4 in der **Struktur vollständig** ab;
der jüngste Prozess-B-Umbau hat die letzte größere Abweichung beseitigt. Offen
sind:

- **G1/G2 (inhaltlich wichtig):** RAG-Frage ist durch die Thesis entschieden
  (kein RAG in der Datenbasis) — meine frühere Auskunft war falsch und ist
  korrigiert. Der Kostenstellen-Agent ist im Prototyp semantischer, als die
  Thesis ihn beschreibt; das ist über eine Textpräzisierung (empfohlen) oder eine
  Prototyp-Umstellung auflösbar.
- **G3 (wichtig, betrifft die Arbeit selbst):** Buchungs-Agent — Text (HITL) und
  Abbildung 5 (on-the-loop) widersprechen sich; das gehört in der Arbeit
  vereinheitlicht, dann der Prototyp danach.
- **G4/G5 (klein, optional):** dynamische Cloud-Eskalation und explizite
  Audit-Felder — nachrüstbar, für die Kernaussagen nicht erforderlich.
