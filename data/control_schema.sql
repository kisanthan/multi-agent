-- Additive control migration. Existing audit rows and target records are retained.
CREATE TABLE IF NOT EXISTS control_versions (version INTEGER PRIMARY KEY, installed_at TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS local_credentials (
 upn TEXT PRIMARY KEY REFERENCES ad_users(upn), salt TEXT NOT NULL, password_hash TEXT NOT NULL,
 active INTEGER NOT NULL DEFAULT 1, failures INTEGER NOT NULL DEFAULT 0, locked_until REAL NOT NULL DEFAULT 0);
CREATE TABLE IF NOT EXISTS auth_sessions (
 token_hash TEXT PRIMARY KEY, upn TEXT NOT NULL REFERENCES ad_users(upn), expires REAL NOT NULL);
CREATE TABLE IF NOT EXISTS controlled_cases (
 case_id TEXT PRIMARY KEY, actor TEXT NOT NULL, document_hash TEXT NOT NULL,
 filename TEXT NOT NULL, process TEXT, stopped INTEGER NOT NULL DEFAULT 0,
 created_at REAL NOT NULL);
CREATE TABLE IF NOT EXISTS case_candidates (
 case_id TEXT NOT NULL REFERENCES controlled_cases(case_id), step TEXT NOT NULL,
 version INTEGER NOT NULL, payload TEXT NOT NULL, payload_hash TEXT NOT NULL,
 approval_required INTEGER NOT NULL, created_at REAL NOT NULL,
 PRIMARY KEY(case_id, step, version));
CREATE TABLE IF NOT EXISTS approvals (
 approval_id TEXT PRIMARY KEY, case_id TEXT NOT NULL, step TEXT NOT NULL, version INTEGER NOT NULL,
 payload_hash TEXT NOT NULL, policy_version TEXT NOT NULL,
 submitter TEXT NOT NULL, approver TEXT, decided_at REAL, expires REAL NOT NULL,
 status TEXT NOT NULL CHECK(status IN ('requested','approved','rejected','expired','revoked','consumed')),
 reason TEXT NOT NULL DEFAULT '', command_id TEXT UNIQUE,
 UNIQUE(case_id, step, version));
CREATE TABLE IF NOT EXISTS execution_commands (
 command_id TEXT PRIMARY KEY, case_id TEXT NOT NULL, step TEXT NOT NULL, version INTEGER NOT NULL,
 payload_hash TEXT NOT NULL, payload TEXT NOT NULL, approval_id TEXT,
 policy_version TEXT NOT NULL, status TEXT NOT NULL
 CHECK(status IN ('prepared','running','succeeded','rejected','in_doubt')),
 receipt TEXT, created_at REAL NOT NULL,
 UNIQUE(case_id, step, version), UNIQUE(approval_id));
CREATE TABLE IF NOT EXISTS scoped_grants (
 token_hash TEXT PRIMARY KEY, command_id TEXT NOT NULL, service TEXT NOT NULL,
 audience TEXT NOT NULL, tool TEXT NOT NULL, expires REAL NOT NULL, used INTEGER NOT NULL DEFAULT 0);
CREATE TABLE IF NOT EXISTS document_objects (
 document_hash TEXT PRIMARY KEY, content BLOB NOT NULL, created_at REAL NOT NULL);
CREATE TABLE IF NOT EXISTS archive_assignments (
 assignment_id TEXT PRIMARY KEY, archive_id TEXT NOT NULL REFERENCES archive(archive_id),
 case_id TEXT NOT NULL, cost_center_id TEXT NOT NULL REFERENCES cost_centers(id),
 filing_plan TEXT NOT NULL, version INTEGER NOT NULL, active INTEGER NOT NULL DEFAULT 1,
 command_id TEXT NOT NULL UNIQUE, created_at REAL NOT NULL);
CREATE UNIQUE INDEX IF NOT EXISTS one_active_assignment ON archive_assignments(archive_id) WHERE active=1;
CREATE TABLE IF NOT EXISTS audit_v2 (
 id INTEGER PRIMARY KEY AUTOINCREMENT, event TEXT NOT NULL, prev_hash TEXT NOT NULL,
 hash TEXT NOT NULL UNIQUE, legacy_event INTEGER NOT NULL UNIQUE REFERENCES audit(id));
CREATE TRIGGER IF NOT EXISTS audit_v2_no_update BEFORE UPDATE ON audit_v2
 BEGIN SELECT RAISE(ABORT, 'Audit V2 is append-only'); END;
CREATE TRIGGER IF NOT EXISTS audit_v2_no_delete BEFORE DELETE ON audit_v2
 BEGIN SELECT RAISE(ABORT, 'Audit V2 is append-only'); END;
CREATE TRIGGER IF NOT EXISTS document_objects_no_update BEFORE UPDATE ON document_objects
 BEGIN SELECT RAISE(ABORT, 'Original documents are immutable'); END;
CREATE TRIGGER IF NOT EXISTS document_objects_no_delete BEFORE DELETE ON document_objects
 BEGIN SELECT RAISE(ABORT, 'Original documents are immutable'); END;
CREATE TABLE IF NOT EXISTS policy_overrides (
 policy_version TEXT PRIMARY KEY, disabled INTEGER NOT NULL DEFAULT 0, reason TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS local_extraction_failures (
 case_id TEXT NOT NULL, step TEXT NOT NULL, reason TEXT NOT NULL, occurred_at REAL NOT NULL,
 PRIMARY KEY(case_id,step));
CREATE TABLE IF NOT EXISTS layout_requests (
 request_id TEXT PRIMARY KEY, case_id TEXT NOT NULL, step TEXT NOT NULL, page INTEGER NOT NULL,
 region TEXT NOT NULL, redactions TEXT NOT NULL, image BLOB NOT NULL, image_hash TEXT NOT NULL,
 prepared_by TEXT NOT NULL, reviewed_by TEXT, reviewed_at REAL, review_reason TEXT,
 status TEXT NOT NULL CHECK(status IN ('prepared','reviewed','sent','succeeded','failed')),
 result TEXT);
