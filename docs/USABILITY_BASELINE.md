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
