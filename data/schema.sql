-- Gemeinsame Datenbasis beider Prozesse (Abschnitt 1 des Fachkonzepts) sowie
-- AD-Mock und Audit-Trail.
--
-- Bewusst eine einzige SQLite-Datei: die Arbeit argumentiert mit einer
-- *gemeinsamen* Stammdatenbasis, auf die beide Prozesse zugreifen. Getrennte
-- Dateien wuerden diese Aussage im Code aufloesen.

PRAGMA journal_mode = WAL;
PRAGMA foreign_keys = ON;

-- ---------------------------------------------------------------- Stammdaten

-- Offene Rechnungen/Bestellungen (Prozess A gleicht hiergegen ab).
CREATE TABLE IF NOT EXISTS rechnungen (
    nummer       TEXT PRIMARY KEY,
    betrag_eur   REAL    NOT NULL CHECK (betrag_eur > 0),
    faellig_am   TEXT    NOT NULL,
    status       TEXT    NOT NULL CHECK (status IN ('offen', 'bezahlt')),
    lieferant_id TEXT    REFERENCES lieferanten (id),
    bezahlt_am   TEXT
);

-- Kostenstellenkatalog (Prozess B ordnet hiergegen zu).
CREATE TABLE IF NOT EXISTS kostenstellen (
    id            TEXT PRIMARY KEY,
    bezeichnung   TEXT NOT NULL,
    -- Eindeutige Referenz, die auf dem Beleg steht und exakt nachgeschlagen
    -- wird (Thesis §7.4: "exakter referenzieller Nachschlag"). Der
    -- Kostenstellen-Agent gleicht die vom Beleg extrahierte Referenz gegen
    -- diese Spalte ab -- deterministisch, kein Sprachmodell.
    referenz      TEXT NOT NULL UNIQUE,
    -- Beschreibende Schluesselwoerter (Metadaten fuer die Klaerfall-Anzeige;
    -- werden fuer die Zuordnung NICHT als Aehnlichkeitsmass verwendet).
    schluesselwoerter TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS lieferanten (
    id     TEXT PRIMARY KEY,
    name   TEXT NOT NULL,
    ustid  TEXT,
    adresse TEXT
);

-- ------------------------------------------------------ AD-Mock (Least Privilege)

CREATE TABLE IF NOT EXISTS ad_nutzer (
    upn      TEXT PRIMARY KEY,   -- User Principal Name, z.B. m.mustermann@chg-meridian.com
    anzeigename TEXT NOT NULL,
    rolle    TEXT NOT NULL       -- 'einspeiser' | 'pruefer' | 'beobachter'
);

CREATE TABLE IF NOT EXISTS ad_gruppen (
    name        TEXT PRIMARY KEY,
    beschreibung TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS ad_mitgliedschaften (
    upn    TEXT NOT NULL REFERENCES ad_nutzer (upn),
    gruppe TEXT NOT NULL REFERENCES ad_gruppen (name),
    PRIMARY KEY (upn, gruppe)
);

-- ------------------------------------------------------------- Zielsysteme (Mocks)

-- Navision (Prozess A) wirkt auf die Tabelle `rechnungen` (Status offen ->
-- bezahlt); eine eigene Buchungstabelle braucht es dafuer nicht.
--
-- ELO (Prozess B): revisionssichere Ablage. Prozessende von Prozess B.
CREATE TABLE IF NOT EXISTS archiv (
    archiv_id    TEXT PRIMARY KEY,
    dateiname    TEXT NOT NULL,
    dokument_hash TEXT NOT NULL,
    abgelegt_am  TEXT NOT NULL
);

-- --------------------------------------------------------------- Audit-Trail

-- Append-only mit Hash-Verkettung: jeder Eintrag hasht den vorherigen.
-- Die Unveraenderlichkeit wird zusaetzlich per Trigger erzwungen (unten), damit
-- ein UPDATE/DELETE nicht bloss "nicht vorgesehen", sondern unmoeglich ist.
CREATE TABLE IF NOT EXISTS audit (
    id           INTEGER PRIMARY KEY AUTOINCREMENT,
    ts           TEXT NOT NULL,
    akteur       TEXT NOT NULL,   -- UPN oder Agent-ID
    agent        TEXT,            -- Agent-ID aus registry.py, NULL bei Systemereignissen
    aktion       TEXT NOT NULL,
    entscheidung TEXT NOT NULL CHECK (entscheidung IN ('erlaubt', 'verweigert', 'info')),
    begruendung  TEXT NOT NULL,
    payload_hash TEXT NOT NULL,
    prev_hash    TEXT NOT NULL,
    hash         TEXT NOT NULL UNIQUE
);

CREATE TRIGGER IF NOT EXISTS audit_kein_update
BEFORE UPDATE ON audit
BEGIN
    SELECT RAISE(ABORT, 'Audit-Trail ist append-only: UPDATE nicht zulaessig');
END;

CREATE TRIGGER IF NOT EXISTS audit_kein_delete
BEFORE DELETE ON audit
BEGIN
    SELECT RAISE(ABORT, 'Audit-Trail ist append-only: DELETE nicht zulaessig');
END;

CREATE INDEX IF NOT EXISTS idx_rechnungen_status ON rechnungen (status);
CREATE INDEX IF NOT EXISTS idx_audit_ts ON audit (ts);
