# Abschlussbericht: Angleichung Prototyp ↔ Masterarbeit

**Datum:** 27.07.2026 · **Branch:** `thesis-angleichung` · **Baseline-Commit:** `db3ba8a`
**Bezug:** `Masterarbeit.docx` (einreichungsreife Fassung, 10 Kapitel, vier Unterfragen), Abschnitt §7.4 „Anwendung und Analyse der Prozessdomänen"

---

## 1. Analysierter Ausgangsstand

**Masterarbeit.** Einreichungsreif seit 27.07.2026 (Abschlussvermerk + Gutachten
im Thesis-Ordner). DSR-Struktur, vier Unterfragen, Fallbeispiel = Kapitel 7,
§7.4 mit vorangestelltem Eignungs-Schritt. Zentral: Die Arbeit rahmt den
Prototyp **bewusst als konzeptionelles Artefakt / Zukunftsarbeit** — §8 bewertet
qualitativ, „da das Artefakt … nicht prototypisch implementiert wurde"; §9.4
nennt die prototypische Umsetzung als Folgeschritt.

**Prototyp.** Lauffähig, LangGraph 1.2, beide Prozesse, Governance-Kern,
hash-verketteter Audit-Trail, Mocks (Navision, ELO), 68 Tests grün vor dieser
Session. Bereits vor dieser Session per Prozess-B-Umbau an das Konzeptdiagramm
(Teil 3) angeglichen.

## 2. Festgestellte Fehler und Widersprüche

- **Meine frühere RAG-Auskunft war falsch.** Ich hatte dem Nutzer geraten, RAG
  passe für die Kostenstellen-Zuordnung. Die Thesis (§7.4) lehnt RAG für die
  Datenbasis **ausdrücklich** ab und begründet das sauber. → korrigiert.
- **Thesis-interner Widerspruch (nicht behoben, dokumentiert):** Buchungs-Agent
  ist im **Text** und in Tabelle 11 „Human-in-the-loop", in **Abbildung 6** aber
  „Human-on-the-loop"; die Bewertungstabelle nennt für Prozess A zugleich
  „manueller Eingriff nur im Ausnahmefall". Das ist in der Arbeit selbst
  aufzulösen (siehe [gap-analyse-thesis.md](gap-analyse-thesis.md) G3).
- **Keine sachlichen Fehler im §7.4-Text gegenüber dem Konzept gefunden** — der
  Abschnitt ist konsistent und (nach dem Prozess-B-Umbau) deckungsgleich mit dem
  Code.

## 3. Abweichungen Masterarbeit ↔ Quellcode und ihre Auflösung

Der Nutzer hat entschieden: **Thesis nicht anfassen** (einreichungsreif), **Code
an die §7.4-Spezifikation angleichen**.

| # | Thesis §7.4 | Code (vorher) | Auflösung (Code jetzt) |
|---|---|---|---|
| D1 | Buchungs-Agent Human-in-the-loop, finanzwirksam | on-the-loop + Betragsschwelle | **immer HITL**, Schwelle entfernt |
| D2 | Kostenstellenzuordnung „exakter referenzieller Nachschlag" | LLM-/schlüsselwortbasiert-semantisch | **deterministischer Referenz-Nachschlag**, kein Modell |
| — | Abgleich = exakter Nachschlag | Registry `LOKAL_KLEIN` (Alt-Inkonsistenz) | Modellklasse `KEINE` (konsistent zu D2) |

## 4. Aus dem Fallbeispiel abgeleitete Anforderungen (§7.4)

1. Zwei Prozesse A/B, gemeinsame Ingestionsstrecke, gemeinsame Datenbasis. ✅
2. Shared Domain Agents; Orchestrator ohne fachliche Vollrechte; Reader kein
   KI-Agent, AD-Sicherheitsgruppe am Eingang. ✅
3. Prozess A: Abgleich → Buchung (Navision, offen→bezahlt), **Buchung unter
   Human-in-the-loop**. ✅ (D1)
4. Prozess B: Kostenstelle → bei eindeutiger Zuordnung direkt ELO, sonst Klärfall
   (Vier-Augen, HITL); **ELO = Prozessende**, keine Navision-Buchung. ✅
5. **Beide Nachschläge (Abgleich, Kostenstelle) exakt referenziell,
   deterministisch, außerhalb des Sprachmodells; kein RAG in der Datenbasis.** ✅
   (D2, I1, I7)
6. Policy deterministisch außerhalb des LLM; Audit protokolliert Auftraggeber,
   Agent, Datenquelle, Tool-Aufruf, Policy-Entscheidung, Ergebnis
   manipulationsgeschützt. ✅ (teilweise, siehe offene Punkte O2)
7. Risikobasierte Modellzuordnung, modellunabhängige Abstraktionsschicht. ✅

## 5. Vorgenommene Änderungen am Quellcode

**D1 — Buchungs-Agent immer Human-in-the-loop**
- `registry.py`: `buchung.aufsicht = HUMAN_IN_THE_LOOP`.
- `governance/policy.py`: Betragsschwellen-Regel entfernt; Buchung läuft über die
  Aufsichtsmodus-Regel → immer `FREIGABE_NOETIG`.
- `config.py`, `.env.example`, `demo.py`, `ui/app.py`: `buchung_schwelle_eur`
  entfernt.
- `agents/buchung.py`: Docstrings aktualisiert.

**D2 — Kostenstelle deterministischer Referenz-Nachschlag**
- `data/schema.sql`: Spalte `kostenstellen.referenz` (unique).
- `data/generate.py`: Referenz-Codes je Kostenstelle (`KTR-…`); Rechnungen tragen
  eine `Kostenstellenreferenz`; Klärfall-Beleg (`B_rechnung_ohne_referenz.pdf`)
  trägt keine.
- `agents/schemas.py`: Feld `Klassifikation.kostenstellen_referenz`;
  `Kostenstellenvorschlag` (LLM) entfernt.
- `agents/kostenstelle.py`: neu als deterministischer Nachschlag (`ordne_zu`),
  kein Modellaufruf.
- `registry.py`: `kostenstelle.modellklasse = KEINE`; ebenso `abgleich` (Konsistenz).
- `llm/client.py`: klarere Fehlermeldung für modelllose Komponenten.
- `graph/state.py`, `graph/workflow.py`: `kostenstellen_referenz` im State;
  `knoten_kostenstelle` nutzt den Nachschlag; Freigabe-Knoten bietet den Katalog.
- `demo.py`, `ui/app.py`: Freigabe-Auswahl aus dem Katalog statt aus LLM-Alternativen.

**Tests**
- `tests/test_policy.py`: Schwellen-Tests → „Buchung immer freigabepflichtig".
- `tests/test_llm.py`: Abgleich/Kostenstelle als modelllose Komponenten.
- `tests/test_szenarien.py`: Szenario 1 (Buchungsfreigabe HITL), Szenario 3
  (Referenz eindeutig → auto), Szenario 4 (Referenz fehlt → Klärfall).

## 6. Überarbeitete Abschnitte der Masterarbeit

**Keine.** Auf Wunsch des Nutzers und wegen der Einreichungsreife bleibt die
`Masterarbeit.docx` unverändert. Alle Angleichungen erfolgten im Code. Die
Prototyp-Doku wurde aktualisiert: `docs/mapping.md` (I1, I2, I5, I7),
`docs/architektur.md`, `README.md`, `docs/gap-analyse-thesis.md`.

## 7. Verbleibende offene Punkte

- **O1 (Arbeit):** Buchungs-Agent-Widerspruch (Text/Tabelle „HITL" vs. Abb. 6
  „on-the-loop"; „Ausnahmefall"-Formulierung). Der Code folgt Text/Tabelle
  (immer HITL). Die Arbeit sollte Abb. 6 und die Automatisierungsgrad-Zeile mit
  dem Text in Einklang bringen. **Entscheidung des Autors.**
- **O2 (klein, Code):** Audit-Felder „Datenquelle" und „Ergebnis" stecken im
  `payload`, nicht als eigene Spalten. Für einen 1:1-Nachweis gegen den
  Thesis-Wortlaut (Kriterium Nachvollziehbarkeit) als eigene Felder führbar.
- **O3 (klein):** dynamische Cloud-Eskalation der Extraktion „bei schwierigen
  Layouts" (Thesis) ist nicht implementiert (statische Modellzuordnung).
- **O4 (Betrieb):** Live-Lauf der Szenarien 1–4 gegen Ollama steht aus
  (Modell-Setup beim Nutzer). Verifikation erfolgt aktuell mit gemocktem Modell.

## 8. Risiken, Annahmen, Empfehlungen

**Annahmen.**
- Die Kostenstellenreferenz ist ein expliziter Beleg-Code (`KTR-…`), den der
  Extraktions-Agent liest. Das ist die Betriebsinterpretation von „exakter
  referenzieller Nachschlag"; die Thesis nennt keine konkrete Referenzform.
- „Buchung immer HITL" folgt dem Thesis-**Text**; die abweichende Abbildung 6
  wird als Thesis-interner, vom Autor zu klärender Widerspruch behandelt.

**Risiken.**
- Wird O1 in der Arbeit zugunsten „on-the-loop" aufgelöst, müsste D1 im Code
  zurückgedreht werden (klein, reversibel über den Branch).
- Der deterministische Kostenstellen-Nachschlag setzt voraus, dass reale Belege
  eine maschinenlesbare Referenz tragen. In der Praxis ist das nicht immer der
  Fall — dann greift der Klärfall häufiger. Das ist fachlich korrekt, sollte in
  `docs/grenzen.md` als Betriebsannahme stehen (ergänzt).

**Empfehlungen.**
- O1 in der Arbeit auflösen (Empfehlung: durchgängig Human-in-the-loop für die
  finanzwirksame Buchung, Abb. 6 anpassen, „Ausnahmefall" auf den Klärfall
  beziehen).
- Prototyp bleibt sauber außerhalb des einzureichenden Kerns (so auch das
  Gutachten §7). Für eine spätere empirische Erweiterung sind die vom Gutachten
  genannten Andockpunkte (§8.2/Tabelle 11 „empirisch offen"-Zellen, §9.4) die
  richtigen Stellen — **erst nach** der Einreichung.
