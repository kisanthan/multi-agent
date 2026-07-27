# Mapping: Fachkonzept → Code

Dieses Dokument bildet die Konzeptartefakte der Arbeit auf den Prototyp-Code ab
und macht jede Interpretationsentscheidung explizit. Es dient als Grundlage für
den Fallbeispiel-Fließtext (Kap. 6).

## Vorbemerkung: fehlende Diagramme

Die sechs Konzeptdiagramme (`uebersicht_gesamt.png`, `mindmap_prozessA/B.png`,
`teil1_agententypen.png`, `teil2_ki_modelle.png`, `teil3_multiagentensystem.png`)
lagen bei der Umsetzung **nicht vor**. Der Prototyp wurde daher nach der
**Agenten-Konfigurationstabelle aus Abschnitt 1 des Planungsprompts** gebaut.
Wo diese Tabelle Spielraum ließ, sind die Entscheidungen unten als
*Interpretation* markiert. Vor der Verwendung in der Thesis sollten diese
Stellen gegen die tatsächlichen Diagramme abgeglichen werden.

## Agenten → Code

| Komponente (Konzept) | Code | Typ | Stufe | Aufsicht | Modellklasse |
|---|---|---|---|---|---|
| Reader-Tool | [tools/reader.py](../tools/reader.py) | kein Agent | – | deterministisch | keine |
| Orchestrator-Agent | `route_dokumenttyp` in [graph/workflow.py](../graph/workflow.py) | Orchestrator | – | Human-on-the-loop | lokal/klein |
| Klassifikation & Extraktion | [agents/klassifikation.py](../agents/klassifikation.py) | Shared Domain | 2 | Human-on-the-loop | vision |
| Abgleich-Agent | [agents/abgleich.py](../agents/abgleich.py) | Shared Domain | 1 | Human-on-the-loop | keine *(det., I1)* |
| Buchungs-Agent | [agents/buchung.py](../agents/buchung.py) | Shared Domain | 3 | **Human-in-the-loop** | Frontier |
| Kostenstellen-Agent | [agents/kostenstelle.py](../agents/kostenstelle.py) | Shared Domain | 2 | Human-on-the-loop | keine *(det., I1)* |
| ELO-Agent (Prozessende B) | [agents/zielsysteme.py](../agents/zielsysteme.py) | Shared Domain | 3 | Human-on-the-loop | lokal/klein |
| Policy-/Governance | [governance/policy.py](../governance/policy.py) | Policy | – | deterministisch | keine |
| Audit-/Monitoring | [governance/audit.py](../governance/audit.py) | Audit | – | read-only | keine |

Die Tabelle ist im Code als wirksame Datenstruktur hinterlegt
([registry.py](../registry.py)) — die Policy liest daraus. Eine Stufe zu ändern
ändert das Laufzeitverhalten; sie ist nicht bloß dokumentiert.

## Diagramme → Realisierung

- **`uebersicht_gesamt.png` (Fluss A+B)** → ein gemeinsamer Graph
  ([graph/workflow.py](../graph/workflow.py)) mit geteiltem Reader, Orchestrator,
  Klassifikation und Datenbasis. Zwei getrennte Graphen hätten die Aussage
  *gemeinsamer* Komponenten aufgelöst.
- **`mindmap_prozessA.png`** → Knoten `reader → klassifikation → abgleich →
  buchung → Navision`, HITL-Knoten `klaerfall` (nur bei unbekannter Nummer /
  Betragsabweichung). Navision setzt den Status offen → bezahlt.
- **`mindmap_prozessB.png`** → Knoten `reader → klassifikation → kostenstelle →
  (bei Mehrdeutigkeit) freigabe_kostenstelle → elo`. **Prozessende bei ELO** —
  keine Navision-Verbuchung in Prozess B (Diagramm Teil 3).
- **`teil1_agententypen.png` (Taxonomie)** → [registry.py](../registry.py):
  `AgentTyp`, `Autonomiestufe`, `Aufsichtsmodus` als Enums.
- **`teil2_ki_modelle.png` (Modellzuordnung)** → `Modellklasse` je Agent plus
  [llm/client.py](../llm/client.py) `waehle_modell`: Risikoklasse × Modus → Anbieter.
- **`teil3_multiagentensystem.png` (Gesamtsynthese, AD + Governance)** → AD-Check
  in [tools/reader.py](../tools/reader.py), Governance-Schicht in `governance/`,
  Schichtgrenze per Test erzwungen.

## Interpretationsentscheidungen

### I1 — Abgleich- und Kostenstellen-Agent ohne Sprachmodell *(mit Nutzer abgestimmt)*

Thesis §7.4: Sowohl der Nummern-Abgleich (Prozess A) als auch die
Kostenstellenzuordnung (Prozess B) sind „exakte, referenzielle Nachschläge auf
strukturierte Stammdaten". Ein Sprachmodell könnte dort nichts beitragen, was ein
Datenbankzugriff nicht exakt und reproduzierbar leistet — es könnte nur
halluzinieren, und das an finanz- bzw. buchungsrelevanter Stelle. Der Prototyp
implementiert beide Agenten deshalb **deterministisch**
([agents/abgleich.py](../agents/abgleich.py),
[agents/kostenstelle.py](../agents/kostenstelle.py)); Autonomiestufe und
Aufsichtsmodus bleiben gültig, die Modellklasse ist `KEINE`. Das Extrahieren der
Nummer bzw. der Kostenstellenreferenz vom Beleg leistet der vorgelagerte
Klassifikations-/Extraktions-Agent (der ein Modell nutzt).

**Verwertbarer Befund für die Arbeit:** Rolle und Autonomiestufe eines Agenten
implizieren nicht automatisch Modellinferenz. Die Typologie sagt, *welche Rolle*
und *welche Autonomiestufe* eine Komponente hat — ob dafür ein Sprachmodell nötig
ist, ist eine davon getrennte Entscheidung. Deterministische Domain-Agenten
(Abgleich, Kostenstelle) stehen damit neben den ohnehin deterministischen
Querschnittskomponenten (Reader, Policy, Audit).

### I2 — Buchungs-Agent: immer Human-in-the-loop (Abgleich mit Thesis §7.4)

Der finanzwirksame Buchungsschritt steht nach Thesis §7.4 und Tabelle 11 unter
**Human-in-the-loop**: jede Buchung erfordert eine menschliche Freigabe,
unabhängig vom Betrag. Eine frühere Prototyp-Fassung nutzte eine Betragsschwelle
(darunter automatisch, darüber Freigabe); diese wurde entfernt, weil sie die im
Konzept geforderte durchgängige Aufsicht abgeschwächt hätte. Realisiert über die
Aufsichtsmodus-Regel in [governance/policy.py](../governance/policy.py).

*(Verbleibende Thesis-interne Spannung: Abb. 6 beschriftet den Buchungs-Agenten
als „Human-on-the-loop", der Text als „Human-in-the-loop"; die Bewertungstabelle
nennt zudem für Prozess A „manueller Eingriff nur im Ausnahmefall". Der Code
folgt dem Text/der Tabelle. Siehe [gap-analyse-thesis.md](gap-analyse-thesis.md)
G3.)*

### I3 — Autonomiestufen „1–2"

Wo die Tabelle einen Bereich nennt, prüft die Policy gegen die **Obergrenze**
(Klassifikation → 2). Begründung: die Policy muss gegen die höchste beanspruchte
Stufe prüfen, sonst wäre die Schranke wirkungslos.

### I4 — Orchestrator routet ohne erneuten Modellaufruf

Der Dokumenttyp steht nach dem Klassifikations-Agenten bereits fest. Der
Orchestrator *routet* danach (Conditional Edge), statt ein zweites Modell zu
fragen — ein zweiter Aufruf könnte dem ersten widersprechen.

### I5 — Kostenstellen-Agent: Human-on-the-loop, HITL nur bei fehlender Referenz

Nach dem Diagramm Teil 3 ist der Kostenstellen-Agent **Human-on-the-loop**: löst
die Belegreferenz eindeutig eine Kostenstelle auf, läuft der Vorgang automatisch
bis zur Archivierung; die Vier-Augen-Freigabe greift nur, wenn die Referenz fehlt
oder unbekannt ist (Entscheidung „Zuordnung eindeutig?" → nein/Klärfall). Das
spiegelt exakt Prozess A (Nummer vorhanden?). Realisiert in
[graph/workflow.py](../graph/workflow.py) über `route_kostenstelle`.

*(Frühere Prototyp-Fassung erzwang an dieser Stelle immer eine Freigabe; das
Diagramm hat den Aufsichtsmodus auf on-the-loop präzisiert.)*

### I6 — Prozess B endet bei ELO (keine Navision-Verbuchung)

Nach dem Diagramm Teil 3 ist die revisionssichere Archivierung in ELO das
**Prozessende** von Prozess B. Eine bilanzwirksame Verbuchung als
Verbindlichkeit (früherer „Navision-Agent", Stufe 4) findet nicht mehr statt.
Navision (NAV) wird nur noch in Prozess A angesprochen (Buchungs-Agent, Status
offen → bezahlt). Der Navision-Agent, der Endpunkt `/liability`, das State-Feld
`verbindlichkeit_id` und die Tabelle `verbindlichkeiten` wurden entfernt.

### I7 — Gemeinsame Datenbasis: kein RAG (Abgleich mit Thesis 6.4)

**Korrektur:** Die Thesis (Abschnitt 6.4, Absatz zu RAG) legt fest, dass die
gemeinsame Datenbasis **bewusst nicht** als RAG-System ausgeführt wird — und
zwar für *beide* Nachschläge: „Der Abgleich im Zahlungseingang und die
Kostenstellenzuordnung in der Eingangsrechnung sind exakte, referenzielle
Nachschläge auf strukturierte Stammdaten." RAG wird in der Arbeit nur als
*komplementäre* Ergänzung gesehen, und zwar an anderer Stelle: zur Unterstützung
des Klassifikations-/Extraktions-Agenten bei ungewöhnlichen Beleglayouts und zur
Anreicherung der menschlichen Klärfallprüfung um Vertrags-/Richtlinienpassagen.

Der Prototyp folgt dieser Linie nun für **beide** Nachschläge: sowohl der
Abgleich-Agent als auch der Kostenstellen-Agent sind deterministische, exakte
Referenz-Nachschläge ohne Sprachmodell (siehe I1). Die frühere Prototyp-Fassung
implementierte die Kostenstellenzuordnung LLM-/schlüsselwortbasiert-semantisch;
das wurde auf einen Referenz-Nachschlag umgestellt, um mit der Thesis-Aussage
konsistent zu sein: Die Rechnung trägt eine Kostenstellenreferenz (z. B.
`KTR-ITINFRA`), der Extraktions-Agent liest sie, der Kostenstellen-Agent schlägt
sie exakt im Katalog nach. „Nicht eindeutig" heißt jetzt: Referenz fehlt oder
unbekannt → Klärfall.

**Verbleibende analytische Spannung (für die Arbeit):** Der Prozessschritt
„Zuordnung eindeutig?" mit Klärfall-Pfad passt nun sauber zum Referenz-Nachschlag
(Referenz vorhanden → eindeutig; fehlt → Klärfall). Die zuvor notierte Spannung
(„ein exakter Nachschlag ist nie mehrdeutig") ist damit aufgelöst: die
„Uneindeutigkeit" liegt nicht in einer semantischen Ähnlichkeit, sondern im
Fehlen der Referenz auf dem Beleg.

## Governance-Durchsetzung

- **Least Privilege:** Der AD-Check liegt *innerhalb* von `lies_dokument()`, vor
  jedem Dateizugriff — nicht im aufrufenden Knoten. Beleg:
  `tests/test_reader.py::test_verweigerter_zugriff_liest_die_datei_nicht`.
- **Deterministische Governance:** `governance/` importiert keinen LLM-Client;
  per AST-Analyse erzwungen (`tests/test_schichtgrenze.py`).
- **Audit-Trail:** hash-verkettet, append-only per DB-Trigger; `verify_chain()`
  erkennt Änderung, Löschung und Einfügung.
