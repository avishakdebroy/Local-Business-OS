# Design notes

Why the code is shaped the way it is. Written for whoever maintains this next.

---

## 1. The central boundary

The package is split by pipeline stage rather than by technical kind:

```
capture/  →  interpretation/  →  ledger/  →  reporting/
(faithful)   (guessing)          (the books)  (summaries)
```

`interpretation/` may guess. `ledger/` may not. Nothing in `interpretation/`
holds a database handle, and nothing in `ledger/` reads free text.

The transition between them is `ledger/posting.py`, and it is the whole point
of the design. An extraction becomes ledger rows only when it is:

1. **complete** — every required field present (`pipeline.blocking_gaps`), and
2. **valid** — passes `posting.validate` (an amount must be positive, VAT
   cannot exceed the total, a date must be a real date), and
3. **trusted** — confidence at or above `LBOS_AUTO_POST_THRESHOLD`, or accepted
   by a person on the review screen.

Failing any of these puts the document in `pending_review`, where it is visible
and excluded from every total. There is no path by which an unreviewed guess
becomes a number the shop owner reads as fact.

## 2. Reading works without a model

`interpretation/rules.py` is the primary reader: keyword and pattern matching
over bilingual vocabulary, with no network call. This is what makes the app
viable on a shop counter PC.

`interpretation/llm.py` is an optional enhancement, off by default. When it is
on, `pipeline._merge` folds its answer into the rules answer:

- it fills fields the rules left blank,
- agreement on the total raises confidence slightly,
- **disagreement on the total or the document type caps confidence at 0.45**,
  which forces review.

Two readers disagreeing is precisely the case a human should see. The model can
never overwrite a rules value or push an entry into the books on its own.

## 3. Numbers

| Kind | Stored as | Why |
|---|---|---|
| Money | `INTEGER` paisa | Float sums drift. A drifting total is worse than no total. |
| Quantity | `INTEGER` milli-units | Shops weigh things; 2.5 kg needs to be exact too. |
| Business date | `TEXT` `YYYY-MM-DD`, local | See below. |
| Audit instant | `TEXT` UTC with `Z` | Ordering only. Never filtered on. |

Bengali numerals are normalised to ASCII once, in `domain/numerals.py`, before
anything tries to parse them. Display uses South Asian digit grouping
(`৳1,23,45,678.90`, not `৳123,456,78.90`).

## 4. Two clocks, never mixed

`captured_at` is when the app saw a document. `entry_date` is when the money or
stock actually moved, as a local date.

**Reports filter on `entry_date` only.** This matters more than it looks:
comparing a UTC instant against a local-time boundary shifts the window by the
timezone offset, which in `Asia/Dhaka` silently drops six hours of entries from
every weekly report — and those hours are the evening close, when a shop
reconciles its day. `tests/test_reporting.py` covers this directly, and
`tests/test_periods.py` proves consecutive windows tile the calendar exactly.

It also means a Saturday sale typed in on Monday lands in Saturday's week.

## 5. The books are append-mostly

Corrections supersede rather than overwrite:

- `money_entries` rows are voided, not updated or deleted. A partial unique
  index (`uq_money_active`) allows exactly one live row per document while
  keeping every superseded version.
- `stock_moves` are voided the same way.
- On-hand stock is a **view** (`item_stock`) that sums live movements. There is
  no stored quantity to drift away from its own history, and a rebuild is free.

`posting.unpost` takes a recorded entry back out of the books and returns it to
review, so a mistake never needs a database edit.

## 6. Duplicate protection

`documents.content_hash` is unique. Text is hashed after whitespace and case
normalisation; **files are hashed by their bytes**, because two unreadable
photos both extract to empty text and must not collapse into one document.

Re-submitting a document is a no-op that says so, rather than doubling the day's
takings.

## 7. SQLite is configured, not assumed

`db/connection.py` sets, on every connection:

- `foreign_keys = ON` — off by default, which would make every `REFERENCES`
  clause in the schema decorative;
- `journal_mode = WAL` — so a scheduled report and an upload do not block
  each other;
- `busy_timeout = 10s` — so contention waits instead of failing.

Schema changes are forward-only numbered files under `db/migrations/`, tracked
in `schema_migrations`. Editing an applied migration is never correct.

## 8. Failures are visible, not silent

- Scheduled jobs run through `ops/scheduler.record_job`, which writes a row to
  `job_runs` whether the job succeeds or fails, and never lets an exception
  escape into APScheduler. A job failing every night for a month shows up on the
  **Status** screen and in the weekly report.
- Report generation and email delivery are separate steps. The report row is
  written *before* delivery is attempted, so a wrong SMTP password costs an
  email, not the report.
- Text extraction never raises. A missing Tesseract, a broken PDF or a scan with
  no text layer all return an empty result plus a warning, and the document is
  still captured for review. Losing a receipt to a missing dependency would be
  far worse than an empty text field.
- Backups return a result object rather than raising, and use SQLite's online
  backup API so a snapshot taken mid-write is still valid.

## 9. Testing

`Settings` is a `pydantic-settings` model constructed explicitly and passed
down; there is no import-time singleton. Tests build one pointed at a
`tmp_path`, which is what makes the 131-test suite possible without touching
`os.environ`.

The tests that matter most are the ones asserting things *do not* happen:
a zero amount cannot be recorded, a duplicate is not counted twice, an
unconfident reading contributes nothing to a total, a boundary day appears in
exactly one week.

## 10. Deliberate omissions

- **Authentication.** Single operator, bound to loopback. Adding accounts to a
  one-person shop tool costs more than it protects.
- **Combined posting.** A sale that also moves stock is recorded as one or the
  other, not both. Doing it properly needs a review UI that can show two
  proposed entries at once; doing it badly would post stock the operator never
  confirmed.
- **Backup encryption.** Delegated to `rclone crypt` and documented as such,
  rather than implemented here where the key management would be worse.
