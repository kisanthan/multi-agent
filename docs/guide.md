# Betriebsanleitung für den lokalen Demonstrator

## 1. Laufzeit vorbereiten

```powershell
python -m venv .venv
.venv\Scripts\python.exe -m pip install -r requirements.txt
Copy-Item .env.example .env
```

`OLLAMA_BASE_URL` muss auf einen lokalen Host zeigen. `demo.py --check` prüft
Erreichbarkeit und Modellnamen, lädt jedoch selbst keine Modelle.

## 2. Portal-Modus auswählen

Im **Admin-Modus** steht in `.env`:

```dotenv
PORTAL_MODE=admin
PORTAL_ADMIN_EMAIL=admin@prototype.local
PORTAL_ADMIN_PASSWORD=Admin-Prototype-2026!
```

Das Konto wird beim ersten Start automatisch angelegt. Das Startpasswort gilt
nur für diesen lokalen Prototyp. Eine Passwortänderung erfolgt mit:

```powershell
.venv\Scripts\python.exe -m governance.identity admin@prototype.local
```

Für die getrennte Freigabe können weitere Konten provisioniert werden:

```powershell
.venv\Scripts\python.exe -m governance.identity m.keller@chg-meridian.com
.venv\Scripts\python.exe -m governance.identity t.brandt@chg-meridian.com
.venv\Scripts\python.exe -m governance.identity s.hofmann@chg-meridian.com
```

Passwörter werden verdeckt abgefragt, mit `scrypt` abgeleitet und niemals im
Checkpoint oder Audit gespeichert. Nach wiederholten Fehlversuchen wird das
lokale Konto zeitweise gesperrt. Die Provisionierung ist eine vertrauensvolle
Bootstrap-Operation auf dem lokalen Rechner.

Im **Demo-Modus** steht in `.env`:

```dotenv
PORTAL_MODE=demo
DEMO_SUBMITTER_UPN=m.keller@chg-meridian.com
DEMO_APPROVER_UPN=s.hofmann@chg-meridian.com
```

Das Portal überspringt die Loginseite und zeigt den Schalter **Demo-Rolle**.
Ein Vorgang wird mit der Einreicherrolle gestartet. Für eine wartende
Freigabe wird zur Prüferrolle gewechselt. Beide Rollen erhalten intern
getrennte Sitzungen; Fremdfreigabe, Payloadbindung und Audit bleiben aktiv.

## 3. Dienste starten

In getrennten PowerShell-Fenstern:

```powershell
.venv\Scripts\python.exe -m uvicorn mocks.navision:app --port 8001
.venv\Scripts\python.exe -m uvicorn mocks.elo:app --port 8002
.venv\Scripts\python.exe -m streamlit run ui/app.py
```

Im Admin-Modus verlangt die Oberfläche Benutzerkennung und Passwort. Für eine
Fremdfreigabe meldet sich die prüfende Person in einem eigenen Browserkontext
oder nach einem Sitzungswechsel an. Im Demo-Modus öffnet sich die Oberfläche
direkt; die Rollen werden über **Demo-Rolle** getrennt. Eine Benutzerkennung in
einem Resume-Payload allein genügt in keinem Modus.

## 4. Vorgänge bearbeiten

- Unter **Neuer Beleg** wird ein synthetisches PDF ausgewählt und gestartet.
- Die Detailansicht zeigt den aktuellen Vorschlag einschließlich
  `approval_id` und Version.
- Prozess A verlangt bei jeder Buchung die Entscheidung einer anderen Person.
- Prozess B archiviert bei einer eindeutigen Referenz direkt. Ohne eindeutige
  Referenz wählt eine andere Person eine Kostenstelle; nach einer inhaltlichen
  Änderung wird der neue Vorschlag nochmals angezeigt und bestätigt.
- Unter **Vorgangsoperationen** können berechtigte Personen einen Fall stoppen,
  fortsetzen, ein `in_doubt`-Kommando prüfen und eine Archivzuordnung
  versioniert korrigieren.

## 5. Layout-Ausnahmeweg

Die Funktion erscheint nur nach einem gespeicherten lokalen
Extraktionsfehler. Die prüfende Person wählt Seite und Rechteck, bestätigt die
Maskierung und kontrolliert den erzeugten PNG-Ausschnitt. Das System versendet
erst, wenn die nicht versionierte `data/layout-deployment.json` auf einen
aktuellen, separat geprüften Nachweissatz verweist. Im ausgelieferten Paket
existiert dieser Nachweis nicht; die Cloud-Ausführung bleibt deshalb gesperrt.

## 6. Störungen

| Anzeige | Bedeutung | Vorgehen |
|---|---|---|
| `zugriff_verweigert` | Anmeldung oder Prozessrecht fehlt | Identität und Gruppenzuordnung prüfen |
| `verworfen` | Vorschlag abgelehnt oder Kontrollvertrag verletzt | Auditgrund lesen; ggf. neuen Vorgang/Vorschlag erzeugen |
| `buchungssystem_nicht_erreichbar` / `in_doubt` | Transportausgang unbekannt | über Vorgangsoperationen den eigenen Receipt prüfen |
| `archivierung_fehlgeschlagen` | ELO hat verbindlich abgelehnt oder war nicht erreichbar | Kommando- und Auditstatus unterscheiden; nicht blind wiederholen |
| Cloud-Layout gesperrt | Nachweis fehlt oder Maskierung nicht bestätigt | keinen Umgehungsweg verwenden; Nachweise außerhalb der Anwendung prüfen |

## 7. Nachweise prüfen

```powershell
.venv\Scripts\python.exe demo.py --audit
.venv\Scripts\python.exe -m pytest -q
```

Der CLI-Auditbefehl zeigt die kompatible Legacy-Kette. Die Tests prüfen
zusätzlich `audit_v2`, Kontrollverträge, Rechteentzug, Replay, Beträge,
Archivversionen und beide Ende-zu-Ende-Prozesse.
