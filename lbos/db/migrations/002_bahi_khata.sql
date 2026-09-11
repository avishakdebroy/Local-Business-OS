-- Bahi khata: the parts of a paper ledger the first schema did not model.
--
-- The largest of these is customer credit. A small shop in Bangladesh sells on
-- বাকি (credit) to regulars every day and tracks it in a notebook; a ledger that
-- cannot answer "who owes me money" is not a bahi khata. As with stock, the
-- balance is DERIVED from entries and never stored, so it cannot drift.

CREATE TABLE customers (
    id         INTEGER PRIMARY KEY AUTOINCREMENT,
    name       TEXT    NOT NULL,
    -- Case- and space-insensitive, so "Rahim Mia" and "rahim  mia" are one person.
    name_key   TEXT    NOT NULL UNIQUE,
    phone      TEXT,
    note       TEXT,
    created_at TEXT    NOT NULL,
    updated_at TEXT    NOT NULL
);

CREATE INDEX idx_customers_name ON customers (name);

-- 'charge' = the shop gave goods and is owed (বাকি).
-- 'payment' = the customer paid some of it back (জমা).
CREATE TABLE credit_entries (
    id           INTEGER PRIMARY KEY AUTOINCREMENT,
    customer_id  INTEGER NOT NULL REFERENCES customers (id),
    document_id  INTEGER REFERENCES documents (id) ON DELETE CASCADE,
    entry_date   TEXT    NOT NULL CHECK (length(entry_date) = 10),
    kind         TEXT    NOT NULL CHECK (kind IN ('charge', 'payment')),
    amount_paisa INTEGER NOT NULL CHECK (amount_paisa > 0),
    note         TEXT,
    voided_at    TEXT,
    void_reason  TEXT,
    created_at   TEXT    NOT NULL
);

CREATE INDEX idx_credit_customer ON credit_entries (customer_id, entry_date);
CREATE INDEX idx_credit_date ON credit_entries (entry_date);

-- Positive balance means the customer owes the shop.
CREATE VIEW customer_balance AS
SELECT
    c.id    AS customer_id,
    c.name  AS name,
    c.phone AS phone,
    COALESCE((
        SELECT SUM(CASE e.kind WHEN 'charge' THEN e.amount_paisa ELSE -e.amount_paisa END)
        FROM credit_entries e
        WHERE e.customer_id = c.id AND e.voided_at IS NULL
    ), 0) AS balance_paisa,
    (SELECT MAX(e.entry_date) FROM credit_entries e
      WHERE e.customer_id = c.id AND e.voided_at IS NULL) AS last_activity,
    (SELECT COUNT(*) FROM credit_entries e
      WHERE e.customer_id = c.id AND e.voided_at IS NULL) AS entry_count
FROM customers c;

-- --- Retail product detail ---------------------------------------------------
-- A cosmetics shelf is brand + product + shade/size. Flattening that into one
-- name makes twelve lipstick shades unbrowsable and prone to mis-merging.
ALTER TABLE items ADD COLUMN barcode TEXT;
ALTER TABLE items ADD COLUMN brand TEXT;
ALTER TABLE items ADD COLUMN variant TEXT;
-- MRP is legally binding in Bangladesh: the shop may not sell above it.
ALTER TABLE items ADD COLUMN mrp_paisa INTEGER;
ALTER TABLE items ADD COLUMN sale_price_paisa INTEGER;

CREATE UNIQUE INDEX uq_items_barcode ON items (barcode) WHERE barcode IS NOT NULL;
CREATE INDEX idx_items_brand ON items (brand);

-- Cosmetics expire. Stock that quietly passes its date is money lost and a
-- reputational risk, so a movement can carry its batch and expiry.
ALTER TABLE stock_moves ADD COLUMN batch_no TEXT;
ALTER TABLE stock_moves ADD COLUMN expiry_date TEXT;
-- Not every movement is a sale or a purchase: testers, breakage and write-offs
-- consume stock without revenue, and they must be visible separately.
ALTER TABLE stock_moves ADD COLUMN reason TEXT NOT NULL DEFAULT 'adjust';

CREATE INDEX idx_stock_expiry ON stock_moves (expiry_date) WHERE expiry_date IS NOT NULL;

-- --- Phone link ---------------------------------------------------------------
-- A phone paired over the shop's own Wi-Fi. No account, no cloud, no internet:
-- the token is minted on the laptop and only ever travels across the LAN.
CREATE TABLE paired_devices (
    id           INTEGER PRIMARY KEY AUTOINCREMENT,
    name         TEXT    NOT NULL,
    token_hash   TEXT    NOT NULL UNIQUE,
    created_at   TEXT    NOT NULL,
    last_seen_at TEXT,
    revoked_at   TEXT
);

-- A short-lived code shown on the laptop screen, exchanged once for a token.
CREATE TABLE pairing_codes (
    code       TEXT PRIMARY KEY,
    expires_at TEXT NOT NULL,
    used_at    TEXT,
    created_at TEXT NOT NULL
);
