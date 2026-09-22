# Soll-Ist-Mapping Masterarbeit → Code

Stand: 21. September 2026

Die Kapitelangaben beziehen sich auf die bereitgestellte Masterarbeit und den
daraus abgeleiteten Soll-Ist-Vergleich. Die Einstufung beschreibt den
prüfbaren Prototypstand und ist keine Aussage über einen Produktivbetrieb.

| Soll aus der Masterarbeit | Kapitel/Abschnitt | Umsetzung | Status |
|---|---|---|---|
| Agentische Rollen und deterministische Dienste mit Sponsor und begrenzten Werkzeugen | Kap. 4; Kap. 6.1; Kap. 7.4 | `agent_registry.py`, `governance/step_policy.py` | umgesetzt im lokalen Register |
| Identity-&-Access-Layer und Least Privilege | Kap. 4.2–4.4; 6.1.1 | `governance/identity.py`, `governance/ad.py`, `runtime/tool_gateway.py` | umgesetzt als lokale Rollensimulation; kein Produktiv-IAM |
| Getrennter Konzept- und Vorführbetrieb | Demonstration und Evaluation des Artefakts | `PortalMode.ADMIN`, `PortalMode.DEMO`, `ui/app.py` | umgesetzt; Demo überspringt nur Login, nicht Prozesskontrollen |
| Schichtentrennung von Orchestrierung, Policy, Audit und Werkzeugen | Kap. 6.1 | `graph/`, `governance/`, `runtime/`, `mocks/` | umgesetzt |
| Human-in-the-loop bei finanziell wirksamer Buchung | Kap. 6.5–6.6; Kap. 7.4; Prozess A | `graph/nodes/payment_confirmation.py`, `governance/control.py` | umgesetzt; jede Buchung benötigt Fremdfreigabe |
| Getrennte Behandlung von Buchungsfreigabe und Dublettenklärung | Kap. 6.5–6.6; Kap. 7.4; Prozess A | `ui/cases/process_views/payment_confirmation.py`, `graph/nodes/payment_confirmation.py` | umgesetzt; bereits bezahlte Posten sind gesperrt und können ohne Buchung als Dublette geschlossen oder nach Korrektur erneut geprüft werden |
| Human-on-the-loop beziehungsweise Ausnahmefreigabe bei Kostenstellenzuordnung | Kap. 6.5–6.6; Kap. 7.4; Prozess B | `graph/nodes/incoming_invoice.py` | umgesetzt; Freigabe nur ohne eindeutige Referenz |
| Schemafehler werden nach dem Retry als Klärfall behandelt | Kap. 6.6, Tabelle 12 | `graph/nodes/shared.py`, `graph/nodes/incoming_invoice.py` | umgesetzt; Dokumenttyp beziehungsweise Rechnungsfelder werden vor der Fachwirkung geprüft |
| Autorisierung darf nicht aus einem LLM oder Checkpoint folgen | Kap. 4.4; 6.1.4–6.1.5 | `governance/step_policy.py`, `governance/control.py` | umgesetzt, Default-Deny |
| Just-in-Time Access und Runtime-Enforcement | Kap. 6.4.3 | `scoped_grants`, `runtime/tool_gateway.py`, `runtime/targets.py` | umgesetzt; Grant höchstens 15 Minuten und einmal verwendbar |
| Strukturierte, objektgebundene Freigabe | Kap. 6.5–6.6 | `case_candidates`, `approvals`, `execution_commands` | umgesetzt mit Fall, Schritt, Version, Hash und Regelversion |
| Idempotente, nachvollziehbare Zielsystemaktion | Kap. 6.4.1–6.4.3 | `runtime/targets.py`, `graph/effects.py` | umgesetzt über Kommando und dauerhaften Receipt |
| Vollständiger Audit Trail | Kap. 6.1.6; 6.5–6.6; Kap. 8 | `governance/audit.py`, `governance/audit_contract.py` | umgesetzt mit Legacy-Kette und `audit_v2` |
| Lokale Standardverarbeitung und kontrollierte Cloud-Ausnahme | Kap. 6.4.2; Kap. 7.4, Tabelle 23 | `governance/inference_policy.py`, `llm/layout.py` | lokale Verarbeitung umgesetzt; Cloud bleibt ohne externe Nachweise gesperrt |
| Datenminimierung und unverändertes Original | Kap. 4.5.3; 6.4.2 | `document_objects`, Raster-/Maskierungsweg | umgesetzt im Prototyp |
| Stoppen, Fortsetzen und kontrollierte Wiederaufnahme | Kap. 6.5; 6.10 | `governance/control.py`, `ui/cases/operations.py` | umgesetzt |
| Versionierte Korrektur einer Archivzuordnung | Prozess B; Nachvollziehbarkeit | `archive_assignments`, `correct_archive_assignment()` | umgesetzt ohne Löschung der Historie |
| Reales Entra-/Unternehmens-IAM | Kap. 6.1.1; 6.4.3 | passwortloser Demo-Rollenwechsel und lokale AD-Simulation | nicht erforderlich; Integrationsgrenze dokumentiert |
| Reale Navision-/ELO-Anbindung | Kap. 6.4.1; Kap. 7.4 | FastAPI/SQLite-Mocks | nicht erforderlich; Schnittstellenverträge demonstriert |
| Belastbare regulatorische Konformitätsbewertung | Kap. 8.3–8.5 | technische Kontrollen und Tests | nicht nachweisbar ohne Organisation, DPIA, Rechtsprüfung und Betriebsevidenz |

## Relevante Tests

| Prüffrage | Testnachweis |
|---|---|
| Kann eine frei gesetzte Benutzerkennung eine Sitzung ersetzen? | `test_raw_identity_does_not_start_a_case` |
| Kann der Einreicher selbst genehmigen? | `test_submitter_cannot_approve_own_candidate` |
| Bleibt eine Freigabe nach Payloadänderung gültig? | `test_changed_payload_requires_new_version_and_approval` |
| Wird ein Rechteentzug vor Ausführung erkannt? | `test_revoked_approver_cannot_authorize_command` |
| Kann ein Grant wiederverwendet oder an ein anderes Ziel gesendet werden? | `test_scoped_grant_is_single_use_and_audience_bound` |
| Führt eine Wiederholung zu einer Doppelbuchung? | `test_target_replay_returns_same_receipt_without_second_effect` |
| Kann eine erkannte Dublette wie eine normale Buchung bestätigt werden? | `test_scenario2b_duplicate_is_flagged_not_rebooked`, `test_duplicate_actions_cannot_look_like_a_posting_approval` |
| Wird Auditmanipulation erkannt? | `test_v2_verifier_detects_rollback_or_missing_tail` |
| Bleibt die Archivkorrektur historisch sichtbar? | `test_archive_correction_versions_assignment_without_deleting_original` |
| Verlässt Standardinferenz den lokalen Rechner? | `test_remote_or_cloud_standard_inference_is_denied` |
| Kann ein vollständiges Dokument in die Layout-Cloud gelangen? | `tests/test_layout_control.py` |
