# How to use Local Business OS
## দোকানের হিসাব রাখার নিয়ম

This guide is for the person running the shop. You do not need to know anything
about computers beyond opening a browser.

---

## 1. Starting and stopping

**To start:** double-click **`start.bat`**. A black window opens and stays
open, and your browser opens the program.

**To stop:** close the black window.

Keep the black window open the whole time you are working. Closing it stops the
program. Nothing is lost when you close it.

---

## 2. Adding an entry

Everything starts on the **Home** screen. There are two boxes.

### Box 1 — Type what happened

Write it the way you would say it, in Bengali or English:

```
বিক্রি ৳১২৫০ নগদ
Bought 20 kg rice from Karim Traders, 1240 taka, bKash
Electricity bill 3400 taka paid
received 20 kg miniket rice
Shop closed early today for the storm
```

You can leave the dropdown on **"Let the app decide"**. Only choose a type
yourself when the app has guessed wrong before on that kind of entry.

### Box 2 — Upload a photo

Take a photo of the receipt with your phone, put it on this computer, and
upload it. JPG, PNG and PDF all work.

**The photo is always kept**, even when the writing cannot be read. If it
cannot be read, the entry goes to the Review screen and you type the details
while looking at the photo.

---

## 3. The Review screen — the important one

After you add an entry, one of two things happens:

- **"Recorded"** — the app was sure, and the entry is in your books.
- **"Waiting for you on the Review screen"** — the app was not sure.

The number next to **Review** at the top of every screen is how many entries
are waiting.

> **Entries waiting for review are not counted in any total.**
> Your Home screen figures and your weekly report only include entries that are
> actually recorded. If the Review number is large, your totals are incomplete.

Open **Review**, click **Check** on an entry, and you will see the original text
or photo on the left and a form on the right. The app fills in what it worked
out and tells you at the top what it was unsure about.

Fix anything that is wrong, then press **Record this**. If the entry is rubbish
— a blurry photo, something added twice — press **Discard**.

### The date field

This is the date on the receipt, **not** today's date. If you are entering
Saturday's sales on Monday, put Saturday's date. Reports are organised by this
date, so getting it right keeps each week's figures correct.

---

## 4. Fixing a mistake later

Nothing is ever permanently wrong.

- Go to **Ledger**, find the entry, press **Undo**.
- The entry leaves your totals and reappears on the Review screen.
- Correct it there and press **Record this** again.

The old version is kept in the file underneath, so there is always a record of
what changed. You never lose history by correcting something.

---

## 5. Stock

Write stock entries like this:

```
received 20 kg miniket rice
sold 5 pcs soap
stock out 3 bottle oil damaged
```

The app works out the item, the quantity, the unit and whether it came in or
went out. If it cannot tell in from out, it will ask you on the Review screen.

On the **Stock** screen you can set a **reorder level** for each item. When the
quantity on hand drops to that level or below, the item is marked **low** on the
Home screen and listed in the weekly report.

The quantity on hand is added up from every movement you have recorded, so it
always matches the history. There is no separate number to correct.

---

## 6. The weekly report

A report is made automatically every **Sunday at 8pm**. You can also press
**"Make this week's report now"** on the **Reports** screen at any time.

The report shows:

- Sales, purchases and the net for the week, compared with the week before
- Where the money went, by category
- How customers paid
- Items running low
- **How many entries are still waiting for review** — because those are not
  in the figures

To have it emailed, fill in the `LBOS_SMTP_*` lines in the `.env` file. If email
is not set up, the report is still made and saved; only the email is skipped.

---

## 7. Backups

Backups happen on their own:

- Every night at 3am — your books and reports
- Every Friday — your books, reports **and all receipt photos**

They are kept in the `data\backups` folder. The 14 most recent of each kind are
kept and older ones are deleted automatically.

**To make one right now:** double-click **`backup-now.bat`**.

**Please also copy the `data` folder to a pen drive or another computer from
time to time.** A backup that lives only on the same machine does not protect
you if the machine is lost or stolen.

---

## 8. Checking that everything is fine

Open the **Status** screen. A green bar means everything is healthy. If
something needs attention it is listed in red with what to do.

Things it checks:

- Whether photo reading is working
- Whether backups are being made, and how much disk space is left
- Whether any scheduled job failed
- Whether the optional AI assist is reachable, if you turned it on

Look at this screen once a week. Nothing on it needs changing day to day.

---

## Common questions

**I added the same receipt twice. Is it counted twice?**
No. The app recognises a document it has already seen and tells you so. Nothing
is added a second time.

**The photo text came out as nonsense.**
Press Discard on the entry, or just fix the fields by hand while looking at the
photo. Better light and a flat, straight photo help a lot.

**Can I use this on my phone?**
Only if someone sets it up for your network. By default the program is reachable
only from the computer it runs on, which is the safe setting.

**Do I need internet?**
Only the first time, to install. After that it works completely offline.
