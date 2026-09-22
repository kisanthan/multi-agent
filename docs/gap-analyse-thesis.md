# Umsetzungsstatus der ursprünglichen Gap-Analyse

Stand: 21. September 2026

Dieses Dokument schließt die vor der Implementierung ermittelten Lücken. Die
Bewertung bezieht sich auf den lokalen Demonstrator.

| Ursprüngliche Lücke | Implementierter Stand | Verbleibende Grenze |
|---|---|---|
| Benutzerkennung war frei auswählbar | Passwortbasierte lokale Sitzung, Token nur gehasht gespeichert, Laufzeitprüfung in Reader und Freigaben | kein Entra/MFA/Conditional Access |
| Checkpoint diente faktisch als Autorisierungszustand | separate Kontrolltabellen für Fall, Kandidat, Freigabe, Kommando und Grant | PostgreSQL-/Workflow-Engine-Integration offen |
| Policy war überwiegend schreibaktionsbezogen | geschlossene `StepPolicy` für jeden registrierten Prozessschritt | organisatorische Policypflege und Rezertifizierung offen |
| Freigabe war nur ein Name im Resume-Payload | strukturierte Fremdfreigabe mit Fall, Aktion, Version, Hash, Ablauf und Regelversion | qualifizierte Unternehmensidentität offen |
| Schreibaufruf besaß keinen Ende-zu-Ende-Idempotenzschlüssel | persistentes Kommando, einmaliger Grant und atomarer Receipt | Hersteller-API-Vertrag offen |
| Timeout konnte als fehlender Effekt interpretiert werden | eigener Zustand `in_doubt` und beleggebundene Wiederaufnahme | automatische Reconciliation/Alerting offen |
| Auditfelder entsprachen den sieben Kategorien nicht vollständig | `audit_v2` mit sieben strukturierten Kategorien und Link zur alten Kette | externer WORM-/SIEM-Speicher offen |
| Cloudprofile konnten unmaskierte Standarddaten erhalten | zentrale Laufzeitsperre; Einstellungsoberfläche bietet für Standardprofile nur lokales Ollama an | alte `.env`-Werte werden kompatibel gelesen, ihre Ausführung wird jedoch blockiert |
| Layout-Ausnahmeweg fehlte | Crop, Rasterisierung, Maskierungsreview, lokale Fehlerbedingung und Nachweissperre | kein aktiver externer Proxy/Nachweissatz ausgeliefert |
| Archivkorrektur war nicht versioniert | aktive Zuordnungsversion mit erhaltener Historie | DMS-spezifische Records-Management-Regeln offen |
| Geldbeträge wurden als Float weitergereicht | Validierung mit `Decimal`, Kommandogrenze in Cent | Währungs- und Rundungsregeln für weitere Länder offen |
| Stop/Fortsetzen und kontrollierte Wiederaufnahme fehlten | Vorgangsoperationen und Auditereignisse implementiert | Betriebsrollen und SLA-Prozess offen |

Die ausführliche Zuordnung zu Kapiteln und Tests steht in `docs/mapping.md`.
