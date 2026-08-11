# Where this stands

Written 2026-08-11. Read this first if you're picking the thread back up cold.

## The three BillRosettas

| | What it is | Where |
| --- | --- | --- |
| **Original** | The product. Flask + React + Tesseract OCR + SQLite. Reads a bill, decodes CPT codes, prices them, drafts one appeal letter. Has accounts, a dashboard, a pitch deck, and a business structure doc. | Local only — `BILLROSETTA-main` folder on the desktop. Never pushed to GitHub. |
| **Moss Bridge** | A hackathon extension, July 18. FastAPI + MCP server, no OCR, no database. Takes CPT codes as JSON and prices them. Its real contribution is `server.py`, a working MCP tool. | `prestigesf/BILLROSETTA` |
| **This repo** | The rate engine. Computes Medicare allowed amounts properly from CMS data. | `prestigesf/medicare-Billrosetta-` |

The first two disagree on real numbers — CPT `80053` is $28.00 in the original
and $45.00 in the Moss build. Both run on small hand-entered tables. Neither
has ever had live CMS data. That's the gap this repo exists to close.

## Open items

**PR #1 on `prestigesf/BILLROSETTA`** — open, draft, mergeable clean, waiting
to be merged. Six fixes to the Moss build: the startup banner printed
"Bright Data Proxy: CONNECTED" with no token; every appeal letter was
subject-lined "RE: Unauthorized Upcoding" (a fraud allegation) with no
threshold behind it; unknown CPT codes were priced at an invented $125
default; negative overcharges reached the letter text; no materiality
threshold; and `mcp[cli]==1.1.2` was pinned, a version that never contained
the module `server.py` imports. 22 tests, up from 12.

**This repo needs three CMS files.** They're public, free, no login:

1. PPRRVU — RVUs and status code per CPT
2. GPCI — the three geographic indices per locality
3. ZIP-to-locality crosswalk

Loaders are deliberately unwritten until the real column layouts are in hand.
Nothing else is blocked.

**Bright Data** was a dead end and can be dropped. It needed a token that was
never issued, and CMS publishes the underlying data in bulk anyway — which is
more accurate, has no per-request cost, and supports pricing by date of
service. The scraper is still in the Moss repo, clearly labelled unproven.

## The direction that was landed on

Sell to **personal injury law firms** before consumers. They already do lien
reduction by hand, they have budget, they buy for the whole practice, and a
firm's letter gets answered where a consumer's often doesn't. Your own
business doc puts that tier at 15:1 CAC-to-LTV against B2C's 4:1.

That changes what to build: **accuracy and provenance over polish**. A firm
needs a number it can defend against opposing counsel, not a pretty UI. OCR
matters less than expected — firms have PDFs and paralegals.

Known complication: PI cases mix professional services (priced under PFS,
covered here) with hospital facility charges (priced under OPPS and DRGs, not
covered). Add OPPS only when firms say it's the blocker.

Unresolved from the business doc: the 2% success fee may run into
fee-splitting rules in CA, TX and FL. Worth a lawyer's read before pricing it.

## Next step

Load the three CMS files. Everything after that — bulk CSV input, a
case-file-ready output — follows from having real rates.
