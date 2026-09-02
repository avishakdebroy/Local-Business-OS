# Local Business OS

Offline-first bookkeeping and inventory for a single shop, running on one
Windows machine. Built for Bangladesh: taka, Bengali and English text, Bengali
numerals, `Asia/Dhaka` business dates, and the payment methods people actually
use (cash, bKash, Nagad, Rocket, card, bank, due).

Single tenant, single operator. No accounts, no cloud service, no internet
required after installation.

---

## Start here

Double-click **`start.bat`**. It installs what it needs the first time, then
opens `http://127.0.0.1:8000` in your browser.

The only prerequisite is [Python 3.11 or newer](https://www.python.org/downloads/),
with **"Add python.exe to PATH"** ticked during its setup.

Day-to-day instructions for the shop are in
**[docs/OPERATOR-GUIDE.md](docs/OPERATOR-GUIDE.md)**.

---

## What it does

1. **Take it in.** Type what happened in Bengali or English, or upload a photo
   or PDF of a receipt.
2. **Read it.** A built-in reader pulls out the date, amount, VAT, who it was
   with, how it was paid, and any stock movement. It needs no AI and no
   internet.
3. **Check it.** Anything the reader is not sure about waits on the **Review**
   screen. Entries waiting for review are never counted in any total.
4. **Keep it.** Sales, purchases, stock movements and notes go into a local
   SQLite file, backed up nightly.
5. **Report it.** A weekly summary is generated every Sunday evening and can be
   emailed.

### The one rule the design is built around

**An automatic reading is a proposal, not a ledger entry.**

A reading reaches the books only when it is complete, valid, and either
confident enough or accepted by a person. When the reader is unsure it lowers
its own confidence and holds the entry — it never invents a value, and it never
writes a zero-amount receipt into your totals. That is why the totals on the
Home screen can be trusted.

---

## Optional extras

Neither is required. The app is fully usable without both.

| Extra | What it adds | How to enable |
|---|---|---|
| **Tesseract OCR** | Reads text out of receipt photos. Without it, photos are still saved — you type the details in. | Install Tesseract with the Bengali language pack, then set `LBOS_TESSERACT_CMD` in `.env` if it is not on PATH. |
| **Ollama** | A local AI model proposes fields alongside the built-in reader. When the two disagree, the entry goes to review. | Install Ollama, pull a model, set `LBOS_LLM_ENABLED=true` in `.env`. |

The **Status** screen tells you whether each is working.

---

## Backups

| What | When | Contains |
|---|---|---|
| Nightly | 03:00 local | Database + reports |
| Weekly | Friday 03:30 local | Database + reports + every uploaded photo |

Backups are written to `data/backups/` and pruned to the newest
`LBOS_BACKUP_KEEP` (default 14) of each kind. The database is copied with
SQLite's online backup API, so a backup taken while you are working is still a
valid, complete database.

To copy backups off the machine, install [rclone](https://rclone.org/), run
`rclone config` to connect free storage, and set `LBOS_RCLONE_REMOTE` in `.env`.
**Use an `rclone crypt` remote** if the storage is not yours — nothing in this
application encrypts the backup itself.

`backup-now.bat` makes a full backup immediately.

---

## For developers

```bash
python -m venv .venv
.venv/bin/pip install -e ".[dev]"      # Windows: .venv\Scripts\pip
.venv/bin/pytest                        # 131 tests
.venv/bin/lbos serve
```

### Layout

The package is organised by pipeline stage, not by technical kind. The
boundary between `interpretation/` (guessing) and `ledger/` (the books) is the
one that matters.

```
lbos/
├── domain/           pure business types: money, quantity, dates. No I/O.
├── capture/          storage and text extraction. Faithful, no interpretation.
├── interpretation/   guessing lives here and nowhere else.
├── ledger/           the books. Every SQL statement in the app is here.
├── reporting/        weekly summary, and emailing it.
├── ops/              backups and scheduled jobs.
├── api/              routers, forms, templates.
├── db/               connection pragmas and forward-only migrations.
├── settings.py       pydantic-settings, injectable.
└── main.py           app factory.
```

Design notes and the reasoning behind each choice:
**[docs/ARCHITECTURE.md](docs/ARCHITECTURE.md)**.

### Command line

```
lbos serve      # run the web app (default)
lbos migrate    # create or update the database, then exit
lbos report     # generate the weekly report now and print it
lbos backup     # make a backup now (--full to include photos)
```

Every setting is an `LBOS_`-prefixed environment variable or a line in `.env`;
see `.env.example`.

---

## Limits worth knowing

- **No authentication.** It binds to `127.0.0.1`, so only this computer can
  reach it. Do not change `LBOS_HOST` to `0.0.0.0` on an untrusted network
  without putting authentication in front of it first.
- **One entry does one thing.** "Sold 5 kg rice for 620 taka" is recorded as a
  sale; the stock movement needs its own entry. Combined posting is not
  implemented.
- **Reader accuracy on photos is unmeasured.** The built-in reader is tested
  against typed text and clean receipts, not against thermal-printer
  photographs. Treat the review queue as the primary interface until you have
  measured how often it is right on your own receipts.
