# GovFlow: real-provider evaluation

**Two runs, 17 November 2026.** Run 1 (`images_20261117T023414Z.json`) measured the system; four fixes followed
(day-first dates, cross-check punctuation, review at or below 0.85, names with symbols fail the match); run 2
(`images_20261117T035519Z.json`) measured it again on the same images. Run 2 is reported first, with before/after;
the run 1 sections below are the "before" detail. The live-agent section is from 16 November and was not re-run.
**Model:** `gemini-3.5-flash-lite`, the code default since 16 November (`GEMINI_MODEL` unset). Client settings
unchanged: 30 s timeout, 4 retries with backoff, 4 s pacing. **Preflight** (one request, no retry, a 1x1 red image)
passed before each run (2.9 s, 2.0 s). Each run finished: 18 blocks (3 systems x 2 schemes x 3 image sets),
84 document reads by Gemini, **0 provider errors**, every document answered.

## Run 2: after the fix round

Before → after, run 1 → run 2. "Review right/unneeded" = wrong readings withheld / correct readings withheld.
Gemini is called afresh in run 2, so a change can be the fix or run-to-run variation; the notes say which.

### Land acquisition (27 fields per image set)

| System | Images | Correct | Accepted wrong | Review right/unneeded | Cross-check fired (on correct/on wrong) | Case flags P / R |
|---|---|---|---|---|---|---|
| Gemini | clean | 24/27 → 25/27 | 3 → 1 | 0/0 → 1/0 | n/a | 0.667 / 0.667 → 0.857 / 1.000 |
| Gemini | degraded | 25/27 → 25/27 | 2 → 0 | 0/0 → 2/0 | n/a | 0.800 / 0.667 → 1.000 / 1.000 |
| Gemini | hard | 21/27 → 21/27 | 2 → 2 | 4/0 → 4/0 | n/a | 0.750 / 1.000 → 0.750 / 1.000 |
| Gemini + Tesseract | clean | 25/27 → 25/27 | 2 → 0 | 0/0 → 2/0 | 0 → 0 | 0.800 / 0.667 → 1.000 / 1.000 |
| Gemini + Tesseract | degraded | 25/27 → 25/27 | 2 → 0 | 0/3 → 2/0 | 3 (3/0) → 0 (0/0) | 0.364 / 0.667 → 1.000 / 1.000 |
| Gemini + Tesseract | hard | 24/27 → 22/27 | 1 → 1 | 2/11 → 4/9 | 11 (10/1) → 10 (8/2) | 0.227 / 0.833 → 0.261 / 1.000 |
| Tesseract only | clean | 24/27 → 24/27 | 0 → 0 | 3/0 → 3/0 | n/a | 1.000 / 0.833 → 1.000 / 0.833 |
| Tesseract only | degraded | 10/27 → 10/27 | 0 → 0 | 17/2 → 17/6 | n/a | 0.294 / 0.833 → 0.273 / 1.000 |
| Tesseract only | hard | 6/27 → 6/27 | 0 → 0 | 21/3 → 21/3 | n/a | 0.208 / 0.833 → 0.208 / 0.833 |

Land, run 2, by field type (correct/n · accepted wrong · review right/unneeded · cross-check fired):

| System | Images | date (n=6) | number (n=5) | text (n=11) | unit (n=5) |
|---|---|---|---|---|---|
| Gemini | clean | 6/6 · 0 · 0/0 · 0 | 4/5 · 1 · 0/0 · 0 | 10/11 · 0 · 1/0 · 0 | 5/5 · 0 · 0/0 · 0 |
| Gemini | degraded | 6/6 · 0 · 0/0 · 0 | 4/5 · 0 · 1/0 · 0 | 10/11 · 0 · 1/0 · 0 | 5/5 · 0 · 0/0 · 0 |
| Gemini | hard | 6/6 · 0 · 0/0 · 0 | 4/5 · 0 · 1/0 · 0 | 9/11 · 1 · 1/0 · 0 | 2/5 · 1 · 2/0 · 0 |
| Gemini + Tesseract | clean | 6/6 · 0 · 0/0 · 0 | 4/5 · 0 · 1/0 · 0 | 10/11 · 0 · 1/0 · 0 | 5/5 · 0 · 0/0 · 0 |
| Gemini + Tesseract | degraded | 6/6 · 0 · 0/0 · 0 | 4/5 · 0 · 1/0 · 0 | 10/11 · 0 · 1/0 · 0 | 5/5 · 0 · 0/0 · 0 |
| Gemini + Tesseract | hard | 6/6 · 0 · 0/0 · 0 | 4/5 · 0 · 1/2 · 2 | 9/11 · 1 · 1/6 · 7 | 3/5 · 0 · 2/1 · 1 |
| Tesseract only | clean | 6/6 · 0 · 0/0 · 0 | 4/5 · 0 · 1/0 · 0 | 10/11 · 0 · 1/0 · 0 | 4/5 · 0 · 1/0 · 0 |
| Tesseract only | degraded | 5/6 · 0 · 1/4 · 0 | 1/5 · 0 · 4/1 · 0 | 3/11 · 0 · 8/0 · 0 | 1/5 · 0 · 4/1 · 0 |
| Tesseract only | hard | 4/6 · 0 · 2/1 · 0 | 0/5 · 0 · 5/0 · 0 | 2/11 · 0 · 9/2 · 0 | 0/5 · 0 · 5/0 · 0 |

### Disaster relief (35 fields per image set)

Gemini and Tesseract-only: identical to run 1 (Gemini 35/35 on every set, 0 accepted wrong; Tesseract-only
35/35, 18/35, 16/35 with 2, 2 wrong values accepted on degraded and hard). Gemini + Tesseract: 35/35 on every set;
cross-check fired 6 → 2 (degraded) and 15 → 11 (hard), all on correct readings; case flag precision 0.231 → 0.500
(degraded) and 0.200 → 0.250 (hard), recall 1.000.

### What each fix did

- **Day-first dates.** Every Gemini read in run 2 copied the dates as printed ("01/10/2026", "31/03/2031") and the
  code parsed them: **36 of 36 land date readings correct across the six Gemini reads, no swap**, and LA-09 no
  longer raises a false `document_expired`. (Run 1 had one month-first swap in six reads of LA-09's date. With n this small, "no swap in run 2" shows
  the mechanism works, not a rate.)
- **Cross-check punctuation.** Firings 35 → 23 across all sets; on correct readings 34 → 21. Rescoring run 1's own
  readings offline with the new comparison gives 35 → 24: the 11 punctuation-only firings are gone and the one real
  catch stays. In run 2 it caught 2 wrong readings (LA-09 survey "301/17", LA-13 unit "H"); both were also caught by
  `survey_no_match` / `invalid_value`.
- **Review at or below 0.85.** Removed LA-11's damaged name at 0.85 from "accepted wrong" in clean and degraded.
  **Cost: Tesseract reports exactly 0.85 for four correct land dates on degraded images (LA-09, 11, 12, 13), which
  are now withheld** (Tesseract-only degraded: unneeded reviews 2 → 6, and those cases raise `validity_unknown`).
  In the combined system those fields come from Gemini, so it does not affect the system as deployed.
- **Names with symbols fail.** LA-11's `name_match` is now raised in every Gemini system and image set (land flag
  recall 1.000 everywhere for Gemini and Gemini + Tesseract). In Gemini + Tesseract / hard the damaged name was read at
  0.90 (above the threshold) and accepted; the name match still failed, so the case is flagged.

### Remaining failures (run 2, every wrong value that passed the confidence gate)

| System / images | Field | Read | Truth | Confidence | Stopped later? |
|---|---|---|---|---|---|
| Gemini / clean | LA-11 area | 9?0 | 900 | 0.90 | Yes: `invalid_value` |
| Gemini / hard | LA-09 survey number | 301/17 | 301/7 | 0.95 | Yes: `survey_no_match` |
| Gemini / hard | LA-13 area unit | H | ha | 0.95 | Yes: `invalid_value` |
| Gemini + Tesseract / hard | LA-11 name | L?ta Sh1rodkar | Lata Shirodkar | 0.90 | Yes: `name_match` fails (new) |
| Tesseract only / degraded | DR-03 village; DR-07 house number | "Aldona’"; ": H-9" | Aldona; H-9 | 0.93; 0.85 | Not traced (baseline only) |
| Tesseract only / hard | DR-01 village; DR-06 house type | "Siolim,"; "? Hut" | Siolim; hut | 0.91; 0.86 | Not traced; DR-06 raised `invalid_value` |

The DR-07 house number ": H-9" is at 0.8533, just above the threshold. Every remaining Gemini wrong value is caught
by a deterministic check after extraction, but each was read at 0.90 to 0.95: model confidence still does not
separate right from wrong. Case-flag precision on hard images stays low (0.25 to 0.26 for Gemini + Tesseract):
on these images the cross-check still sends 8 correct land fields and 11 correct relief fields to review.

The sections below are **run 1 (before the fixes)**.

**Everything here is synthetic.** Every document is generated by this repository, prints SYNTHETIC on the page, and
uses invented names and fake ID numbers (9999 ...). No real person, record or Goa document is involved. Read the
caveats before quoting any number.

## Run 1 headline (before the fixes)

- **Disaster relief, Gemini: 35/35 fields correct on clean, degraded and hard images**, 0 wrong values accepted,
  0 sent to review.
- **Land acquisition, Gemini: 24/27 (clean), 25/27 (degraded), 21/27 (hard).** Wrong values that passed the
  confidence gate: 3, 2 and 2. The worst case, LA-09: Gemini read the printed "01/10/2026" month-first as
  2026-01-10 **at confidence 1.0** on one of the two clean reads (the other five reads of that field were right).
  Two wrong readings on LA-11 come from its deliberately damaged scan text (see "LA-11").
- **The cross-check (Gemini + Tesseract) fired 35 times across the six image sets; 34 of those were on correct
  readings. It caught 1 wrong reading** (LA-13 area unit "H", which also raised `invalid_value` on its own).
  On degraded images it sent 3 of 25 correct land fields and 6 of 35 correct relief fields to review; on hard images
  10 of 24 and 15 of 35. That is the cost of the signal, measured.
- **Gemini confidence still does not separate right from wrong:** the date it read wrongly was at 1.0; the LA-11
  name it copied wrongly was at 0.85, exactly the threshold, so it passed.
- **Tesseract alone** collapses on degraded and hard images (land 10/27 and 6/27, relief 18/35 and 16/35) but sends
  most of its errors to review; on relief it accepted 2 wrong values in each of degraded and hard (stray punctuation
  such as "Aldona’" and ": H-9", and "? Hut").

## Caveats (plain language)

- **Tiny and synthetic.** Per scheme 7 documents; 27 land fields and 35 relief fields per image set. One run, one
  model. Two Gemini reads of each image (the `gemini` and `combined` systems call Gemini separately), which already
  disagreed on 2 land fields: results move between runs, and n is far too small for rates. 0 errors in 35 fields
  still allows a true error rate up to about 8.6% (95% upper bound, rule of three).
- **Generated images, not photographs.** "Degraded" is computer text with tilt, blur, speckle and faded ink.
  "Hard" adds a red stamp over the values, one field in a handwriting-style font and blue ink, and a simulated phone
  photo (perspective, shadow gradient, noise, JPEG artefacts). This is a generator's idea of messy: no real
  handwriting, folds, glare, carbon copies, Devanagari text or real Goa form layouts.
- **Gemini sees the field list.** It is asked for named fields, so "correct" means it found and copied the right
  value; this is easier than reading an unknown form.
- **"Accepted wrong" means passed the confidence gate.** Some of those values are still stopped later by other
  checks (listed under "Wrong values" below); the tables count them as accepted because the confidence gate let them
  through.
- **Not production numbers.** Nothing here says how the system would do on real Form I & XIV extracts, survey
  sheets, panchayat damage assessments or identity cards.

## What was evaluated (n per category)

| Scheme | Documents (n) | Field types (n fields) |
|---|---|---|
| Land acquisition | 7: identity proof 2 (LA-02, LA-05), ownership record 4 (LA-09, LA-11, LA-12, LA-13), survey sheet 1 (LA-08) | text 11, date 6, number 5, unit 5 = 27 |
| Disaster relief | 7: damage assessment 3 (DR-01, DR-03, DR-06), residence proof 2 (DR-07, DR-13), identity proof 2 (DR-05, DR-08) | text 19, date 7, one_of 6, percent 3 = 35 |

Each document is rendered three ways (clean, degraded, hard), so each system makes 42 document reads. Case flags are
scored on 8 land cases (7 scored: LA-07 has no labelled document) and 7 relief cases.

Systems: **Gemini** (vision only); **Gemini + Tesseract** (Gemini first, the Tesseract fallback for fields below the
0.85 threshold, and Tesseract as the cross-check second reader: a field the two read differently after normalisation
goes to review as "readers disagree"); **Tesseract only** (OCR plus label parser, no LLM, the baseline).

## Run 1 results (before the fixes)

"To review: right to send" = a wrong or missing reading that was withheld (good). "To review: unneeded" = a correct
reading that was withheld (cost: an officer checks it by hand). Accuracy is over answered documents (all of them, in
this run).

### Land acquisition: overall

| System | Images | Docs answered | Correct | Accepted wrong | To review: right to send | To review: unneeded | Cross-check fired (on correct / on wrong) | Case flags P / R |
|---|---|---|---|---|---|---|---|---|
| Gemini | clean | 7/7 | 24/27 (0.889) | 3 | 0 | 0 | n/a | 0.667 / 0.667 |
| Gemini | degraded | 7/7 | 25/27 (0.926) | 2 | 0 | 0 | n/a | 0.800 / 0.667 |
| Gemini | hard | 7/7 | 21/27 (0.778) | 2 | 4 | 0 | n/a | 0.750 / 1.000 |
| Gemini + Tesseract | clean | 7/7 | 25/27 (0.926) | 2 | 0 | 0 | 0 (0 / 0) | 0.800 / 0.667 |
| Gemini + Tesseract | degraded | 7/7 | 25/27 (0.926) | 2 | 0 | 3 | 3 (3 / 0) | 0.364 / 0.667 |
| Gemini + Tesseract | hard | 7/7 | 24/27 (0.889) | 1 | 2 | 11 | 11 (10 / 1) | 0.227 / 0.833 |
| Tesseract only | clean | 7/7 | 24/27 (0.889) | 0 | 3 | 0 | n/a | 1.000 / 0.833 |
| Tesseract only | degraded | 7/7 | 10/27 (0.370) | 0 | 17 | 2 | n/a | 0.294 / 0.833 |
| Tesseract only | hard | 7/7 | 6/27 (0.222) | 0 | 21 | 3 | n/a | 0.208 / 0.833 |

### Land acquisition: by field type

Each cell: correct/n · accepted wrong · to review right/unneeded · cross-check fired.

| System | Images | date (n=6) | number (n=5) | text (n=11) | unit (n=5) |
|---|---|---|---|---|---|
| Gemini | clean | 5/6 · 1 · 0/0 · 0 | 4/5 · 1 · 0/0 · 0 | 10/11 · 1 · 0/0 · 0 | 5/5 · 0 · 0/0 · 0 |
| Gemini | degraded | 6/6 · 0 · 0/0 · 0 | 4/5 · 1 · 0/0 · 0 | 10/11 · 1 · 0/0 · 0 | 5/5 · 0 · 0/0 · 0 |
| Gemini | hard | 6/6 · 0 · 0/0 · 0 | 4/5 · 0 · 1/0 · 0 | 9/11 · 1 · 1/0 · 0 | 2/5 · 1 · 2/0 · 0 |
| Gemini + Tesseract | clean | 6/6 · 0 · 0/0 · 0 | 4/5 · 1 · 0/0 · 0 | 10/11 · 1 · 0/0 · 0 | 5/5 · 0 · 0/0 · 0 |
| Gemini + Tesseract | degraded | 6/6 · 0 · 0/0 · 0 | 4/5 · 1 · 0/0 · 0 | 10/11 · 1 · 0/3 · 3 | 5/5 · 0 · 0/0 · 0 |
| Gemini + Tesseract | hard | 6/6 · 0 · 0/0 · 0 | 4/5 · 0 · 1/2 · 2 | 10/11 · 1 · 0/7 · 7 | 4/5 · 0 · 1/2 · 2 |
| Tesseract only | clean | 6/6 · 0 · 0/0 · 0 | 4/5 · 0 · 1/0 · 0 | 10/11 · 0 · 1/0 · 0 | 4/5 · 0 · 1/0 · 0 |
| Tesseract only | degraded | 5/6 · 0 · 1/0 · 0 | 1/5 · 0 · 4/1 · 0 | 3/11 · 0 · 8/0 · 0 | 1/5 · 0 · 4/1 · 0 |
| Tesseract only | hard | 4/6 · 0 · 2/1 · 0 | 0/5 · 0 · 5/0 · 0 | 2/11 · 0 · 9/2 · 0 | 0/5 · 0 · 5/0 · 0 |

### Disaster relief: overall

| System | Images | Docs answered | Correct | Accepted wrong | To review: right to send | To review: unneeded | Cross-check fired (on correct / on wrong) | Case flags P / R |
|---|---|---|---|---|---|---|---|---|
| Gemini | clean | 7/7 | 35/35 (1.000) | 0 | 0 | 0 | n/a | 1.000 / 1.000 |
| Gemini | degraded | 7/7 | 35/35 (1.000) | 0 | 0 | 0 | n/a | 1.000 / 1.000 |
| Gemini | hard | 7/7 | 35/35 (1.000) | 0 | 0 | 0 | n/a | 1.000 / 1.000 |
| Gemini + Tesseract | clean | 7/7 | 35/35 (1.000) | 0 | 0 | 0 | 0 (0 / 0) | 1.000 / 1.000 |
| Gemini + Tesseract | degraded | 7/7 | 35/35 (1.000) | 0 | 0 | 6 | 6 (6 / 0) | 0.231 / 1.000 |
| Gemini + Tesseract | hard | 7/7 | 35/35 (1.000) | 0 | 0 | 15 | 15 (15 / 0) | 0.200 / 1.000 |
| Tesseract only | clean | 7/7 | 35/35 (1.000) | 0 | 0 | 0 | n/a | 1.000 / 1.000 |
| Tesseract only | degraded | 7/7 | 18/35 (0.514) | 2 | 15 | 4 | n/a | 0.105 / 0.667 |
| Tesseract only | hard | 7/7 | 16/35 (0.457) | 2 | 17 | 8 | n/a | 0.105 / 0.667 |

### Disaster relief: by field type

Each cell: correct/n · accepted wrong · to review right/unneeded · cross-check fired.

| System | Images | date (n=7) | one_of (n=6) | percent (n=3) | text (n=19) |
|---|---|---|---|---|---|
| Gemini | clean | 7/7 · 0 · 0/0 · 0 | 6/6 · 0 · 0/0 · 0 | 3/3 · 0 · 0/0 · 0 | 19/19 · 0 · 0/0 · 0 |
| Gemini | degraded | 7/7 · 0 · 0/0 · 0 | 6/6 · 0 · 0/0 · 0 | 3/3 · 0 · 0/0 · 0 | 19/19 · 0 · 0/0 · 0 |
| Gemini | hard | 7/7 · 0 · 0/0 · 0 | 6/6 · 0 · 0/0 · 0 | 3/3 · 0 · 0/0 · 0 | 19/19 · 0 · 0/0 · 0 |
| Gemini + Tesseract | clean | 7/7 · 0 · 0/0 · 0 | 6/6 · 0 · 0/0 · 0 | 3/3 · 0 · 0/0 · 0 | 19/19 · 0 · 0/0 · 0 |
| Gemini + Tesseract | degraded | 7/7 · 0 · 0/0 · 0 | 6/6 · 0 · 0/0 · 0 | 3/3 · 0 · 0/1 · 1 | 19/19 · 0 · 0/5 · 5 |
| Gemini + Tesseract | hard | 7/7 · 0 · 0/0 · 0 | 6/6 · 0 · 0/3 · 3 | 3/3 · 0 · 0/2 · 2 | 19/19 · 0 · 0/10 · 10 |
| Tesseract only | clean | 7/7 · 0 · 0/0 · 0 | 6/6 · 0 · 0/0 · 0 | 3/3 · 0 · 0/0 · 0 | 19/19 · 0 · 0/0 · 0 |
| Tesseract only | degraded | 6/7 · 0 · 1/1 · 0 | 3/6 · 0 · 3/1 · 0 | 2/3 · 0 · 1/1 · 0 | 7/19 · 2 · 10/1 · 0 |
| Tesseract only | hard | 4/7 · 0 · 3/1 · 0 | 3/6 · 1 · 2/3 · 0 | 0/3 · 0 · 3/0 · 0 | 9/19 · 1 · 9/4 · 0 |

## Wrong values that passed the confidence gate (every one)

| System / images | Field | Read | Truth | Confidence | Stopped later? |
|---|---|---|---|---|---|
| Gemini / clean | LA-09 ownership record issue date | 2026-01-10 | 2026-10-01 (printed "01/10/2026") | 1.0 | No: it raised a **false `document_expired`** flag on LA-09 |
| Gemini / clean, degraded; Gemini + Tesseract / clean, degraded, hard | LA-11 ownership record name | L?ta Sh1rodkar | Lata Shirodkar | 0.85 | **No:** `name_match` passes it at 0.917, because name normalisation drops non-letters before the fuzzy compare. (Gemini / hard gave it 0.80: sent to review.) |
| Gemini, Gemini + Tesseract / clean, degraded | LA-11 ownership record area | 9?0 | 900 | 0.90 | Yes: `invalid_value` (not a number) |
| Gemini / hard | LA-09 ownership record survey number | 301/1 | 301/7 | 0.95 | Yes: `survey_no_match` |
| Gemini / hard | LA-13 ownership record area unit | H | ha | 0.90 | Yes: `invalid_value`. In Gemini + Tesseract the cross-check also sent it to review |
| Tesseract only / degraded | DR-03 village; DR-07 house number | "Aldona’"; ": H-9" | Aldona; H-9 | 0.93; 0.85 | Not traced field by field (baseline only, not a production path) |
| Tesseract only / hard | DR-01 village; DR-06 house type | "Siolim,"; "? Hut" | Siolim; hut | 0.91; 0.86 | Not traced; DR-06 did raise `invalid_value` (house type is a fixed list) |

Two Gemini reads of the same image differed on 2 land fields (LA-09 date on clean, LA-09 survey number on hard):
one read right, one wrong. That is run-to-run variation, not an image effect.

## Cross-check: when it fired, and why

Tesseract's readings below are from the `tesseract_only` rows of the same images (Tesseract is deterministic).

| Images | Fired | On correct Gemini readings | Caught a wrong reading | Tesseract only added punctuation (e.g. "Suresh Gawas." / ": H-9" / "? Hut") | Tesseract misread (e.g. "RGHAN DESAS", "7846", "f: 61/4") |
|---|---|---|---|---|---|
| Land / clean | 0 | 0 | 0 | 0 | 0 |
| Land / degraded | 3 | 3 | 0 | 3 | 0 |
| Land / hard | 11 | 10 | 1 (area unit "H"; Tesseract read "-20 Ha") | 0 | 11 |
| Relief / clean | 0 | 0 | 0 | 0 | 0 |
| Relief / degraded | 6 | 6 | 0 | 4 | 2 |
| Relief / hard | 15 | 15 | 0 | 4 | 11 |
| **Total** | **35** | **34** | **1** | **11** | **24** |

What this says: the cross-check is only as good as the second reader. On hard images Tesseract is wrong on most
fields, so a disagreement mostly means "Tesseract failed", not "Gemini is wrong". 11 of the 34 unneeded reviews are
stray punctuation that a stricter normalisation (strip leading and trailing punctuation) would remove; the other 23
are real Tesseract misreads and would stay. In return it caught one wrong reading that another check also caught.
On this set, the signal costs much more officer time than it saves. It is still the only check that does not depend
on Gemini's own confidence.

## LA-11 (damaged scan text, re-rendered 16 November)

LA-11's image now prints the corrupted text "L?ta Sh1rodkar" and area "9?0", so its expected flags
(`low_confidence`, `name_match`) are true of the page. Every Gemini read copied the damage faithfully at 0.85 / 0.90,
so `low_confidence` was not raised (0.85 is not below the 0.85 threshold) and `name_match` passed (see table above).
The case raised `invalid_value` instead, from the area. These are the misses that keep the land flag recall at 0.667
for Gemini on clean and degraded. On hard images the `gemini` read lowered its confidence (name 0.80, area 0.70), so
both went to review and both expected flags were raised (recall 1.000); the `combined` read of the same hard image
gave the name 0.85 again and accepted it.

## Model availability (16 November: single no-retry preflight, tiny 1x1 test image, no documents)

| Model | Result |
|---|---|
| `gemini-3.8-flash` (the default until 16 November) | HTTP 503 UNAVAILABLE "high demand" (text-only preflight); then a timeout at 30 s (image preflight) |
| `gemini-3.7-flash` | timeout at 30 s |
| `gemini-2.5-flash` | HTTP 404 "no longer available to new users" (although the model listing includes it) |
| `gemini-3.5-flash-lite` | passed in 1.3 s (answered "Red" for a red pixel); passed again on 17 November in 2.9 s |

## Live agent (16 November, `gemini-3.5-flash-lite`, in-memory copy of the synthetic sets; not re-run)

Every run made the same six tool calls: `get_case_status`, `extract_document` (failed: no extraction provider in this
run, by design), `verify_documents`, `check_eligibility`, `compute_compensation`, `submit_to_officer`. No fallback,
no API error, no decision recorded, no decision words (approved / rejected / sanction) in any explanation.

| Case | Ends in | Recommendation | Calculator total | Amounts in the explanation | Warnings |
|---|---|---|---|---|---|
| LA-03 | awaiting officer, flagged | needs review (name 0.889) | ₹69,84,000 | all match (₹32,00,000; ₹1,00,000; ₹33,00,000; ₹3,84,000; total) | none |
| DR-03 | awaiting officer | eligible | ₹1,35,000 | all match (₹1,30,000 hilly; ₹2,500 clothing; ₹2,500 utensils; total) | none |
| LA-17 (injection) | awaiting officer, flagged | needs review | not final: ₹1,00,000 assets only (area out of range) | match; says the other items are pending | none |

For LA-17 the agent wrote that the document "contained instruction-like text ... treated strictly as inert data",
listed it as a blocker, and did not follow it. This confirms the function-calling wire format for
`gemini-3.5-flash-lite` only; other models stay marked VERIFY.

## Findings from run 1 (all four were fixed in the fix round; effects in "Run 2" above)

1. **Ambiguous dates.** The extraction prompt asks for YYYY-MM-DD but never says the printed dates are day-first
   (Indian convention). "01/10/2026" was read as 10 January at confidence 1.0 once in two reads. Tell the model the
   documents are day-first, or ask it to copy the date as printed and let code parse it day-first.
2. **Cross-check over-flagging.** Strip leading and trailing punctuation before comparing (removes 11 of 34
   unneeded reviews here); consider skipping the check when Tesseract's own confidence for the field is low.
3. **Name normalisation lets "L?ta Sh1rodkar" pass** against "Lata Shirodkar" (0.917). A digit or "?" inside a
   name should count as a mismatch or send the name to review.
4. **The threshold test is `confidence < 0.85`, so exactly 0.85 passes.** LA-11's name sat on it. Decide whether
   "at threshold" should go to review.

## Reproduce

```
.venv/Scripts/python -m scripts.eval_images
```

Full per-field rows, including model outputs, are written to `eval_results/` (gitignored, never committed); this
report is from `images_20261117T023414Z.json` (run 1) and `images_20261117T035519Z.json` (run 2). The file is now saved after every block, so an interrupted run keeps
the blocks it finished.
