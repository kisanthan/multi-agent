# Lokale Logprüfung des Abgabestands

Stand: 21. September 2026

## Geprüfte Quellen

- vollständiger Pytest-Lauf mit JUnit-Bericht
- Python-Compileall
- Git-Diff-Prüfung auf Whitespace-Fehler
- lokale Uvicorn- und Streamlit-Logs unter `.runtime_logs`

## Ergebnis

Der vollständige Abnahmelauf bestand mit 393 Tests ohne Fehler oder
Überspringungen. Compileall und `git diff --check` wurden ohne Fehler
abgeschlossen.

Die lokalen Laufzeitlogs enthalten zwei historische Gruppen. Erstens trat am
14. September ein `AttributeError` für die damals noch fehlende Einstellung
`portal_mode` auf. Die Einstellung ist im aktuellen Stand vorhanden und durch
die Portalmodus- und UI-Tests abgedeckt; der Fehler ist damit für den
Abgabestand nicht reproduzierbar. Zweitens enthalten ältere Streamlit-Logs
einen Windows-Verbindungsreset eines Clients. Dieser Eintrag betrifft den
Transportabbruch einer Benutzersitzung und begründet ohne erneutes Auftreten
keinen Anwendungsfehler.

Eine Sentry-, GlitchTip- oder andere Remote-Monitoring-Verbindung ist im
Projekt nicht konfiguriert. Die Abschlussprüfung stützt sich daher auf lokale
Logs und die reproduzierbaren Test-, Compile- und Diff-Nachweise.
