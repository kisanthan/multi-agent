-- Shared master data for both processes (section 1 of the functional
-- concept), plus the AD mock and the audit trail.
--
-- Deliberately a single SQLite file: the thesis argues for a *shared*
-- master-data basis that both processes access. Separate files would
-- dissolve that statement in the code.

PRAGMA journal_mode = WAL;
PRAGMA foreign_keys = ON;

-- ---------------------------------------------------------------- Master data

-- Open invoices/orders (process A reconciles against this).
CREATE TABLE IF NOT EXISTS invoices (
    number       TEXT PRIMARY KEY,
    amount_eur   REAL    NOT NULL CHECK (amount_eur > 0),
    due_date     TEXT    NOT NULL,
    status       TEXT    NOT NULL CHECK (status IN ('offen', 'bezahlt')),
    supplier_id  TEXT    REFERENCES suppliers (id),
    paid_at      TEXT
);

-- Cost-center catalog (process B assigns against this).
CREATE TABLE IF NOT EXISTS cost_centers (
    id            TEXT PRIMARY KEY,
    name          TEXT NOT NULL,
    -- Unique reference printed on the document and looked up exactly
    -- (Thesis §7.4: "exact referential lookup"). The cost-center agent
    -- matches the reference extracted from the document against this
    -- column -- deterministic, no language model.
    reference     TEXT NOT NULL UNIQUE,
    -- Descriptive keywords (metadata for the exception-case display; NOT
    -- used as a similarity measure for the assignment itself).
    keywords      TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS suppliers (
    id      TEXT PRIMARY KEY,
    name    TEXT NOT NULL,
    vat_id  TEXT,
    address TEXT
);

-- ------------------------------------------------------ AD mock (Least Privilege)

CREATE TABLE IF NOT EXISTS ad_users (
    upn          TEXT PRIMARY KEY,   -- User Principal Name, e.g. m.mustermann@chg-meridian.com
    display_name TEXT NOT NULL,
    role         TEXT NOT NULL       -- 'einspeiser' | 'pruefer' | 'beobachter'
);

CREATE TABLE IF NOT EXISTS ad_groups (
    name        TEXT PRIMARY KEY,
    description TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS ad_memberships (
    upn        TEXT NOT NULL REFERENCES ad_users (upn),
    group_name TEXT NOT NULL REFERENCES ad_groups (name),
    PRIMARY KEY (upn, group_name)
);

-- ------------------------------------------------------------------- Intake

-- An uploaded file. Deliberately its own entity and not the same thing as a
-- case: the same file can be processed more than once (re-run), and who
-- submitted it and when cannot be reconstructed from the filesystem alone.
--
-- The *case* itself deliberately does NOT live here -- it stays in the
-- LangGraph checkpoint, where it survives the process and waits for the
-- human. A case table here would be a second source of truth.
CREATE TABLE IF NOT EXISTS uploads (
    upload_id     TEXT PRIMARY KEY,
    filename      TEXT NOT NULL,
    path          TEXT NOT NULL,
    file_type     TEXT NOT NULL,
    size_bytes    INTEGER NOT NULL CHECK (size_bytes > 0),
    content_hash  TEXT NOT NULL,   -- SHA-256, detects re-uploads of the same file
    uploaded_by   TEXT NOT NULL,
    uploaded_at   TEXT NOT NULL,
    check_result  TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_uploads_hash ON uploads (content_hash);

-- ------------------------------------------------------------- Target systems (mocks)

-- Navision (process A) acts on the `invoices` table (status open ->
-- paid); it needs no booking table of its own for that.
--
-- ELO (process B): tamper-evident archive. End of process B.
CREATE TABLE IF NOT EXISTS archive (
    archive_id    TEXT PRIMARY KEY,
    filename      TEXT NOT NULL,
    document_hash TEXT NOT NULL,
    filed_at      TEXT NOT NULL
);

-- --------------------------------------------------------------- Audit trail

-- Append-only with hash chaining: every entry hashes its predecessor.
-- Immutability is additionally enforced via trigger (below), so that an
-- UPDATE/DELETE is not merely "not intended" but impossible.
-- The field list follows the thesis's wording: requester (actor), agent,
-- source, tool call (action), policy decision, and outcome.
-- `case_id`, `source`, and `outcome` feed into the hash -- if they were
-- excluded, exactly the fields that carry the evidentiary value could be
-- forged.
CREATE TABLE IF NOT EXISTS audit (
    id           INTEGER PRIMARY KEY AUTOINCREMENT,
    ts           TEXT NOT NULL,
    actor        TEXT NOT NULL,   -- UPN or agent ID
    agent        TEXT,            -- agent ID from agent_registry.py, NULL for system events
    action       TEXT NOT NULL,
    decision     TEXT NOT NULL CHECK (decision IN ('erlaubt', 'verweigert', 'info')),
    reason       TEXT NOT NULL,
    case_id      TEXT,            -- thread ID of the case, NULL for system events
    source       TEXT,            -- document/file the action relates to
    outcome      TEXT,            -- business outcome of the action
    payload_hash TEXT NOT NULL,
    prev_hash    TEXT NOT NULL,
    hash         TEXT NOT NULL UNIQUE
);

CREATE TRIGGER IF NOT EXISTS audit_no_update
BEFORE UPDATE ON audit
BEGIN
    SELECT RAISE(ABORT, 'Audit-Trail ist append-only: UPDATE nicht zulaessig');
END;

CREATE TRIGGER IF NOT EXISTS audit_no_delete
BEFORE DELETE ON audit
BEGIN
    SELECT RAISE(ABORT, 'Audit-Trail ist append-only: DELETE nicht zulaessig');
END;

CREATE INDEX IF NOT EXISTS idx_invoices_status ON invoices (status);
CREATE INDEX IF NOT EXISTS idx_audit_ts ON audit (ts);
CREATE INDEX IF NOT EXISTS idx_audit_case ON audit (case_id);
