# Grenzen und offene Produktivanforderungen

Stand: 21. September 2026

Der Code belegt die Ausführbarkeit ausgewählter Architektur- und
Kontrollentscheidungen. Er belegt weder die Wirksamkeit unter realer Last noch
die regulatorische Konformität eines späteren Produktivsystems.

1. **Identität:** Admin-Anmeldung, Sperre, Sitzung und Gruppenprüfung sind lokal
   in SQLite umgesetzt. Der Demo-Modus stellt bewusst keine Authentifizierung
   dar; er gibt nur synthetische Rollen für eine kontrollierte Vorführung aus.
   Föderation, MFA, Conditional Access, verwaltete Agentenidentitäten,
   Rezertifizierung und Joiner-Mover-Leaver-Prozesse fehlen.
2. **Zielsysteme:** Navision und ELO sind lokale Mocks. Netzwerksegmentierung,
   produktive API-Verträge, Herstellertransaktionen, Schlüsselrotation,
   Backpressure und Disaster Recovery sind nicht geprüft.
   Der ELO-Mock belegt Dokumenthash, versionierte Zuordnung und erhaltene
   Historie, aber keine produktive Revisionssicherheit. Diese entsteht erst
   durch ein entsprechend konfiguriertes und geprüftes Zielsystem.
3. **Modelle:** Die Tests ersetzen Modellantworten deterministisch. Aussagen zu
   Extraktionsgüte, Robustheit, Bias, Sprachabdeckung und realen Dokumenttypen
   sind daher nicht ableitbar.
4. **Cloud-Layoutanalyse:** Der Code enthält den technisch kontrollierten
   Ausnahmeweg, aber absichtlich keinen aktiven externen Deploymentnachweis und
   keine Anbieterzugangsdaten. Ohne geprüften internen Proxy, EU-Region,
   Auftragsverarbeitung, Löschkonzept und No-Training-Nachweis bleibt der Weg
   geschlossen.
5. **Datenschutz:** Datenminimierung, lokaler Standardweg und Auditfelder sind
   technische Bausteine. Rechtsgrundlage, Verzeichnis der
   Verarbeitungstätigkeiten, Datenschutz-Folgenabschätzung, Betroffenenrechte,
   Aufbewahrung und Löschung erfordern organisatorische Festlegungen.
6. **Audit:** Hashketten und Trigger erschweren unbemerkte lokale Manipulation.
   Ein von Administratoren unabhängiger WORM-Speicher, externe Zeitquelle,
   Signatur, SIEM-Anbindung und Alarmierung fehlen.
7. **Betrieb:** Stop/Fortsetzen und `in_doubt`-Wiederaufnahme sind vorhanden.
   Hochverfügbarkeit, Mehrknoten-Konkurrenz, Queueing, SLOs, Monitoring,
   Incident-Prozesse und regelmäßige Restore-Tests sind nicht umgesetzt.
8. **Skalierung:** SQLite eignet sich für die Demonstration. Sperrverhalten,
   Isolation und Durchsatz eines produktiven Mehrbenutzersystems sind damit
   nicht bewertet.
9. **Regulatorische Einordnung:** Der Prototyp implementiert Anschlussstellen
   für menschliche Aufsicht, Nachvollziehbarkeit und Risikobegrenzung. Die
   konkrete Einstufung nach EU AI Act, DSGVO, NIST AI RMF oder ISO/IEC 42001
   hängt von Zweck, Daten, Betreiberorganisation und Einsatzkontext ab und
   muss separat bewertet werden.
10. **Legacy-Zustand:** Alte Checkpoints ohne kontrollierten Vorgang und
    strukturierte Freigabe werden nicht ausgeführt. Sie müssen neu eingereicht
    oder mit einem separat geprüften Migrationsverfahren übernommen werden.
11. **Demonstrierter Agentenumfang:** Modellnutzend sind Klassifikation und
    prozessspezifische Extraktion. Personal Agents, optionaler Planner und
    freie Agent-zu-Agent-Kommunikation bleiben Bestandteile des Zielbilds und
    werden nicht durch den Prototyp nachgewiesen.
12. **Policy-Änderungen:** Die ausführbare StepPolicy ist geschlossen,
    versioniert und standardmäßig verweigernd. Änderungen erfolgen im
    Prototyp über einen geprüften Code- und Releasewechsel; ein eigener
    Laufzeitworkflow mit Antrag, unabhängiger Freigabe und Aktivierung ist
    nicht implementiert.
13. **Menschliche Freigabekapazität:** Die Benutzeroberfläche trennt reguläre
    Buchungsfreigaben von der Klärung erkannter Dubletten und benennt die
    jeweilige Wirkung. Der Prototyp untersucht jedoch weder Bearbeitungszeiten
    noch Vertretungslasten oder Approval Fatigue. Diese Faktoren müssen in
    einem realen Betrieb organisatorisch und empirisch bewertet werden.
