# Usability baseline (branch `simplify`)

Goal: a juror or officer understands each page in five seconds. Measured, not judged: clicks and scroll distance for
five real tasks, before and after the UI simplification.

## How it is measured

- Script: `web/e2e/usability.mjs` (real app, not mocked). Fresh `python -m scripts.seed_demo --reset` (47 cases), the
  API on port 8000 started with `GEMINI_API_KEY=` empty, so the document pre-check uses its offline fallback and every
  run gives the same result. Viewport 1280 x 800, Chrome.
- Clicks: every click, tick, or click into a field is 1; a native select is 2 (open, choose); a file chooser is 1.
  Typing is not counted. Officer tasks start signed in on the queue; sign-in is not counted.
- Scroll: on each page, how far below the fold (800 px) the deepest thing the user must see or press sits, with the
  page at the top: `max(0, bottom - 800)`. Summed over the pages of the task. A sticky bar that is always on screen
  counts 0.
- Raw output with every step: `docs/usability/before.json` (and `after.json`).
- Screenshots of every page at 1280 and 390 px: `docs/screenshots/simplify/before/` (and `after/`). The tracking
  code field is cleared before its screenshot.

## Before (commit on `simplify` before any UI change, 20 Nov 2026)

| # | Task | Clicks | Scroll (px) | Where the scroll goes |
|---|------|-------:|------------:|------------------------|
| 1 | Officer finds why a case is flagged and its total (LA-18) | 1 | 491 | 491 to find LA-18 in the queue; flag and total are above the fold on the case page |
| 2 | Officer approves a clean case (LA-16) | 5 | 4,740 | 1,468 to find LA-16 in the queue; 3,272 down the case page to the decision panel (Approve, 2 value ticks, Record decision) |
| 3 | Manager checks how many cases are overdue | 1 | 0 | Overdue tile is in the first row of analytics |
| 4 | Citizen checks a document before applying | 4 | 438 | The document check sits below the self-check form |
| 5 | Citizen tracks a file (LA-01) | 5 | 0 | Two fields and a button, result above the fold |

Page heights at 1280 px (full page): queue 2,461; case LA-18 4,395; case LA-16 3,976; case RM-02 5,028; analytics
3,442; self-check 1,369; award letter 1,304. At 390 px: case LA-18 6,542; LA-16 5,842; RM-02 7,933; analytics 5,600;
queue 4,888.

What the numbers say: the officer's main job (task 2) is the slowest by far; the decision panel is the last of nine
sections. Finding a case in the queue costs scroll because the queue lists every case with seven columns.

## After (branch `simplify`, same script, fresh `--reset` seed, 20 Nov 2026)

| # | Task | Clicks before | Clicks after | Scroll before (px) | Scroll after (px) | What changed |
|---|------|--------------:|-------------:|-------------------:|------------------:|--------------|
| 1 | Officer finds why LA-18 is flagged and its total | 1 | 1 | 491 | 494 | Case page: flag and total at the top, as before. The queue scroll to LA-18 is unchanged (same 47 rows, same API order); +3 px from the view buttons |
| 2 | Officer approves clean case LA-16 | 5 | 5 | 4,740 | 1,398 | The decision bar is on screen from the first view (case page 3,272 → 0). What is left is finding LA-16, a clean case near the end of the queue |
| 3 | Manager checks how many cases are overdue | 1 | 1 | 0 | 0 | Overdue is one of four headline numbers |
| 4 | Citizen checks a document before applying | 4 | 5 | 438 | 70 | One part at a time: one click on *Check a document* replaces scrolling past the questions |
| 5 | Citizen tracks a file (LA-01) | 5 | 5 | 0 | 0 | Progress line added; the basis of each amount sits behind *Why?* |
| | **Total** | **16** | **17** | **5,669** | **1,962** | Scroll −65%; one extra click (task 4) |

Default page height (full page, nothing expanded):

| Page | 1280 px before → after | 390 px before → after |
|------|-----------------------|----------------------|
| Case LA-18 (flagged) | 4,395 → 1,086 (−75%) | 6,542 → 1,694 (−74%) |
| Case LA-16 (clean) | 3,976 → 940 (−76%) | 5,842 → 1,452 (−75%) |
| Case RM-02 (mutation, no amount) | 5,028 → 1,013 (−80%) | 7,933 → 1,538 (−81%) |
| Analytics | 3,442 → 1,042 (−70%) | 5,600 → 2,139 (−62%) |
| Self-check | 1,369 → 807 (−41%) | 1,819 → 1,178 (−35%) |
| Queue | 2,461 → 2,370 (−4%) | 4,888 → 4,635 (−5%) |
| Citizen home | 800 → 800 | 905 → 1,076 (+19%: the new three-step *How it works*) |

Target met: the default case page is at least 50% shorter (74–81%). Intake, audit, simulator and the award letter
were already one screen at 1280 px; they changed in spacing only (no shadows, the simulator table scrolls in its own
box on a phone) and their heights are unchanged; the award letter's print layout is untouched.

Not improved, and why: finding a particular clean case in a 47-case queue (tasks 1 and 2) still costs scroll. The
API's order (flags first, then oldest) is kept; the new one-click views narrow to *Needs attention* or *Overdue*, and
the status filter narrows to *Awaiting officer decision*, but the measured route does not use them. A search box was
not added: none existed, and the brief said to add one only if it did.

Screenshot note: full-page screenshots draw the sticky decision bar where it sits in the first 800 px of the window,
over one collapsed row; scrolling moves the page under it, and at the end of the page it returns to its place.
