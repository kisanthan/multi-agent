# Kontrollverträge und Betriebszustände

## Verbindliche Objekte

| Objekt | Bindung | Sicherheitswirkung |
|---|---|---|
| `controlled_cases` | Fall, Einreicher, Dokumenthash, Prozess, Stopstatus | trennt Kontrollzustand vom Checkpoint |
| `case_candidates` | Fall, Schritt, Version, kanonischer Payload-Hash | Änderungen erzwingen eine neue Version |
| `approvals` | Kandidat, Prüfer, Regelversion, Ablauf, Entscheidung | fremde, berechtigte Person; einmaliger Verbrauch |
| `execution_commands` | Kandidat, Freigabe, Payload, Status, Receipt | Idempotenz und `in_doubt`-Behandlung |
| `scoped_grants` | Kommando, Empfänger, Tokenhash, Ablauf | kurzlebiges, einmaliges Zielsystemrecht |
| `document_objects` | SHA-256 und Originalbytes | unverändertes Ausgangsdokument |
| `archive_assignments` | Archiv, Fall, Kostenstelle, Version, Aktivstatus | nachvollziehbare Korrektur ohne Löschung |
| `audit_v2` | sieben Kategorien, Legacy-Link, Hashkette | strukturierter Manipulationsnachweis |

## Portalmodi

`PORTAL_MODE=admin` nutzt die lokale Passwortgrenze. Das beim ersten Start
installierte Administratorkonto besitzt alle drei menschlichen Portalrechte,
darf wegen der Fremdfreigaberegel aber keinen selbst eingereichten Vorschlag
bestätigen. `PORTAL_MODE=demo` überspringt die Passwortabfrage ausschließlich
für die konfigurierten synthetischen Einreicher- und Prüferidentitäten. Die
ausgestellten Demositzungen werden wie normale Sitzungen gehasht gespeichert
und durchlaufen danach unverändert die folgenden Kontrollverträge.

## Zustandsregeln

- `pending`: Ein Kommando ist vorbereitet, aber noch nicht gesendet.
- `in_doubt`: Der Transportausgang ist unbekannt. Es darf keine Behauptung
  über einen fehlenden Effekt abgeleitet werden.
- `succeeded`: Ein eigener, passender Zielsystem-Receipt liegt vor.
- `rejected`: Das Zielsystem hat die Aktion verbindlich ohne Effekt abgelehnt.

Ein erfolgreicher Receipt enthält die `command_id`. Die Oberfläche liest
Zielsystemeffekte ausschließlich über den zum Vorgang gehörenden erfolgreichen
Kommando-Receipt.

## Regelversion

Die ausführbare Matrix trägt die Version `THESIS-20260914-v2`. Ein
Freigabenachweis aus einer anderen oder deaktivierten Regelversion wird nicht
verwendet. Das Entfernen einer Agentenberechtigung, Deaktivieren einer
Identität oder Stoppen eines Falls wirkt vor dem nächsten externen Effekt.

## Auditkategorien

Jedes kontrollierte Ereignis enthält:

1. Einreicher beziehungsweise handelnde Identität,
2. ausführende Komponente,
3. Daten- oder Ereignisquelle,
4. Werkzeug und Aktion,
5. Policy-Entscheidung mit Regelversion,
6. Freigabestatus mit Entscheider und Payload-Hash,
7. Ergebnis einschließlich Kommando- oder Receiptbezug.

Der neue Datensatz verweist zusätzlich auf den Hash des kompatiblen
Legacy-Eintrags. Beide Ketten lassen sich unabhängig verifizieren.
