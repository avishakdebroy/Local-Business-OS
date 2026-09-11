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

**The day book is the home screen** — one page per day, the way the paper ledger
reads, with the day's cash position at the bottom. **The khata** answers the
question a shopkeeper asks most: *who owes me money?*

1. **Take it in.** Type what happened in Bengali or English, upload a photo
   or PDF of a receipt, or send one from your phone.
2. **Read it.** A built-in reader pulls out the date, amount, VAT, who it was
   with, how it was paid, and any stock movement. It needs no AI and no
   internet.
3. **Check it.** Anything the reader is not sure about waits on the **Review**
   screen. Entries waiting for review are never counted in any total.
4. **Keep it.** Sales, purchases, stock movements and notes go into a local
   SQLite file, backed up nightly.
5. **Report it.** A weekly summary is generated every Sunday evening and can be
   emailed.

### Credit — the বাকি খাতা

Selling on credit to regulars is the normal way a small shop trades, so it is a
first-class part of the ledger rather than a note in the margin:

- Every customer has a page: credit given, payments received, running balance.
- The home screen shows the total owed to you, and who owes it.
- **Credit is never counted as cash.** Goods given on বাকি are revenue, but no
  money entered the drawer, and a day book that blurs the two teaches the owner
  to over-count the day's takings. The two figures sit side by side.
- A payment larger than the balance is refused, with the real balance named —
  because that is almost always a typo, and a silent negative balance hides it.
- Balances are derived from entries, never stored, so they cannot drift.

### The one rule the design is built around

**An automatic reading is a proposal, not a ledger entry.**

A reading reaches the books only when it is complete, valid, and either
confident enough or accepted by a person. When the reader is unsure it lowers
its own confidence and holds the entry — it never invents a value, and it never
writes a zero-amount receipt into your totals. That is why the totals on the
Home screen can be trusted.

---

## Using your phone

Switch on `LBOS_PHONE_LINK_ENABLED=true` and a **Phone** screen appears on the
computer showing a QR code. Point your phone's ordinary camera at it and the
phone is linked.

A linked phone can:

- **Photograph a product barcode.** The computer reads the number and finds the
  product, or offers to add it.
- **Photograph a page of your notebook or a supplier's bill.** It goes to the
  Review screen on the computer, where you confirm it before it counts.
- **See today's figures**, read only.

A linked phone **cannot** change the books, remove entries, or reach the backup
and settings screens. Those stay on the computer.

### How it works, and what it does not do

- Your phone and the computer talk **over your own Wi-Fi only**. Nothing goes to
  the internet, there is no account, and no data leaves the shop.
- Turning the link on makes the computer listen on the network. Requests that do
  not come from the computer itself are confined to the phone pages and must
  present a token issued by pairing; everything else is refused.
- The pairing code lasts ten minutes and works once. You can unlink any phone,
  or all of them, from the Phone screen at any time.
- The threat model is your shop's Wi-Fi, not the open internet. Do not put this
  on a public network.

Barcodes are read **on the computer**, from a photo. A browser can only open the
camera for live scanning over HTTPS, which would mean certificates no shopkeeper
should be asked to install — so the phone simply takes a picture through the
normal camera button and sends it.

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

**Copy it to a pen drive.** The Status screen lists any drive that is plugged in
and copies the most recent backup onto it with one press. A backup that lives
only on the shop's one laptop protects against almost nothing — the realistic
disasters are the laptop being stolen, dropped, or having its disk fail. The app
says so on the Status screen until a drive has been used.

## When something goes wrong

The **Status** screen is the one place to look:

- It lists anything wrong in plain language, with what to do about it.
- **Repair** checks the database, applies any pending updates and tidies up. It
  never deletes anything.
- **Download the help file** makes a small zip (around 1–2 KB) describing the
  installation and the recent errors, which the owner can send on WhatsApp to
  whoever helps them. It contains **no** customer names, amounts, phone numbers
  or passwords — it is safe to send. That size matters: a multi-megabyte log
  dump would never finish uploading on a rural connection.

---

## For developers

```bash
python -m venv .venv
.venv/bin/pip install -e ".[dev]"      # Windows: .venv\Scripts\pip
.venv/bin/pytest                        # 200 tests
.venv/bin/ruff check .                  # lint
.venv/bin/lbos serve
```

CI runs the same two commands on every push and pull request, across Python
3.11/3.12/3.13 on Linux plus 3.12 on Windows — Windows being the deployment
target, where path handling and console encoding differ.

### Layout

The package is organised by pipeline stage, not by technical kind. The
boundary between `interpretation/` (guessing) and `ledger/` (the books) is the
one that matters.

```
lbos/
├── domain/           pure business types: money, quantity, dates. No I/O.
├── capture/          storage, text extraction, barcode reading. No interpretation.
├── interpretation/   guessing lives here and nowhere else.
├── ledger/           the books, including customer credit. All SQL is here.
├── reporting/        day book, weekly summary, and emailing it.
├── ops/              backups, scheduled jobs, support bundle and repair.
├── phone/            LAN pairing for the shopkeeper's phone.
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
- **No counter sell screen yet.** Entries are captured, not rung up. A
  scan-to-cart screen is the next major piece.
- **Reader accuracy on photos is unmeasured.** The built-in reader is tested
  against typed text and clean receipts, not against thermal-printer
  photographs. Treat the review queue as the primary interface until you have
  measured how often it is right on your own receipts.
