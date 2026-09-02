-- Initial schema for Local Business OS.
--
-- Conventions used throughout:
--   * Money is INTEGER paisa (1/100 BDT). Never REAL.
--   * Quantities are INTEGER milli-units (1/1000). Never REAL.
--   * entry_date is a LOCAL business date 'YYYY-MM-DD' and is what reports filter on.
--   * created_at / captured_at are UTC instants, for audit ordering only.

-- Every captured document, whether or not it ever reaches the books.
CREATE TABLE documents (
    id               INTEGER PRIMARY KEY AUTOINCREMENT,
    -- SHA-256 of the normalised source. Makes re-uploading the same receipt a
    -- no-op instead of double-counting the day's takings.
    content_hash     TEXT    NOT NULL UNIQUE,
    source_kind      TEXT    NOT NULL CHECK (source_kind IN ('text', 'file')),
    original_filename TEXT,
    stored_path      TEXT,
    raw_text         TEXT    NOT NULL,
    doc_type         TEXT    NOT NULL CHECK (doc_type IN ('sale', 'purchase', 'stock', 'memo')),
    status           TEXT    NOT NULL CHECK (status IN ('pending_review', 'posted', 'rejected')),
    confidence       REAL    NOT NULL DEFAULT 0 CHECK (confidence BETWEEN 0 AND 1),
    extractor        TEXT    NOT NULL DEFAULT 'rules',
    extraction_json  TEXT    NOT NULL DEFAULT '{}',
    captured_at      TEXT    NOT NULL,
    reviewed_at      TEXT,
    review_note      TEXT
);

CREATE INDEX idx_documents_status ON documents (status, id DESC);
CREATE INDEX idx_documents_captured ON documents (captured_at DESC);

-- Sales and purchases. One row per posted money document.
CREATE TABLE money_entries (
    id             INTEGER PRIMARY KEY AUTOINCREMENT,
    document_id    INTEGER NOT NULL REFERENCES documents (id) ON DELETE CASCADE,
    entry_date     TEXT    NOT NULL CHECK (length(entry_date) = 10),
    direction      TEXT    NOT NULL CHECK (direction IN ('sale', 'purchase')),
    party          TEXT,
    total_paisa    INTEGER NOT NULL CHECK (total_paisa >= 0),
    tax_paisa      INTEGER NOT NULL DEFAULT 0 CHECK (tax_paisa >= 0),
    currency       TEXT    NOT NULL DEFAULT 'BDT',
    category       TEXT,
    payment_method TEXT,
    notes          TEXT,
    -- Entries are voided, never deleted: the books stay auditable.
    voided_at      TEXT,
    void_reason    TEXT,
    created_at     TEXT    NOT NULL
);

-- A document has at most one *live* entry, but its superseded versions stay in
-- the table so a correction leaves an audit trail instead of erasing history.
CREATE UNIQUE INDEX uq_money_active ON money_entries (document_id) WHERE voided_at IS NULL;
CREATE INDEX idx_money_entry_date ON money_entries (entry_date);
CREATE INDEX idx_money_direction_date ON money_entries (direction, entry_date);

-- Catalogue of things the shop stocks.
CREATE TABLE items (
    id                  INTEGER PRIMARY KEY AUTOINCREMENT,
    sku                 TEXT    UNIQUE,
    name                TEXT    NOT NULL,
    -- Case- and space-insensitive key, so "Miniket Rice" and "miniket  rice"
    -- do not become two items.
    name_key            TEXT    NOT NULL UNIQUE,
    unit                TEXT    NOT NULL DEFAULT 'pcs',
    reorder_level_milli INTEGER NOT NULL DEFAULT 0 CHECK (reorder_level_milli >= 0),
    created_at          TEXT    NOT NULL,
    updated_at          TEXT    NOT NULL
);

-- Stock movements. On-hand quantity is derived from these, never stored, so it
-- can always be rebuilt and can never drift away from its own history.
CREATE TABLE stock_moves (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    item_id         INTEGER NOT NULL REFERENCES items (id),
    document_id     INTEGER REFERENCES documents (id) ON DELETE CASCADE,
    entry_date      TEXT    NOT NULL CHECK (length(entry_date) = 10),
    direction       TEXT    NOT NULL CHECK (direction IN ('in', 'out')),
    qty_milli       INTEGER NOT NULL CHECK (qty_milli > 0),
    unit_cost_paisa INTEGER CHECK (unit_cost_paisa IS NULL OR unit_cost_paisa >= 0),
    notes           TEXT,
    voided_at       TEXT,
    void_reason     TEXT,
    created_at      TEXT    NOT NULL
);

CREATE INDEX idx_stock_moves_item ON stock_moves (item_id, entry_date);
CREATE INDEX idx_stock_moves_date ON stock_moves (entry_date);
CREATE INDEX idx_stock_moves_document ON stock_moves (document_id);

CREATE VIEW item_stock AS
SELECT
    i.id                  AS item_id,
    i.sku                 AS sku,
    i.name                AS name,
    i.unit                AS unit,
    i.reorder_level_milli AS reorder_level_milli,
    COALESCE((
        SELECT SUM(CASE m.direction WHEN 'in' THEN m.qty_milli ELSE -m.qty_milli END)
        FROM stock_moves m
        WHERE m.item_id = i.id AND m.voided_at IS NULL
    ), 0) AS on_hand_milli
FROM items i;

-- Free-text notes kept alongside the books.
CREATE TABLE memos (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    document_id INTEGER NOT NULL UNIQUE REFERENCES documents (id) ON DELETE CASCADE,
    entry_date  TEXT    NOT NULL CHECK (length(entry_date) = 10),
    title       TEXT    NOT NULL,
    body        TEXT    NOT NULL,
    tags        TEXT    NOT NULL DEFAULT '',
    created_at  TEXT    NOT NULL
);

CREATE INDEX idx_memos_entry_date ON memos (entry_date);

-- One row per generated report.
CREATE TABLE report_runs (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    period_start    TEXT    NOT NULL,
    period_end      TEXT    NOT NULL,
    report_path     TEXT,
    summary_json    TEXT    NOT NULL,
    delivery_status TEXT    NOT NULL DEFAULT 'not_attempted',
    delivery_detail TEXT,
    created_at      TEXT    NOT NULL
);

CREATE INDEX idx_report_runs_period ON report_runs (period_end DESC);

-- Scheduled work leaves a trace here so a job that has been failing every night
-- for a month is visible on screen instead of only in a log nobody reads.
CREATE TABLE job_runs (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    job_name    TEXT NOT NULL,
    status      TEXT NOT NULL CHECK (status IN ('ok', 'error')),
    detail      TEXT,
    started_at  TEXT NOT NULL,
    finished_at TEXT NOT NULL
);

CREATE INDEX idx_job_runs_name ON job_runs (job_name, id DESC);
