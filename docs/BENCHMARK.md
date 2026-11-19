# Processing-time benchmark

Run on 2026-11-19 with `python -m scripts.benchmark_processing`. Times are in milliseconds.

- **Machine:** Windows 11 (10.0.26300), AMD64 Family 25 Model 97 Stepping 2, AuthenticAMD, 32 logical CPUs; Python 3.12.10
- **Provider:** fallback provider: Tesseract reads alone (Gemini preflight did not pass: Gemini request timed out)
- **Cases:** 42 synthetic cases; 14 document images read (clean variant)

| Scheme | Stage | n | Median | Mean | 90th percentile |
|---|---|---|---|---|---|
| disaster_relief | read | 7 | 547.7 | 570.3 | 900.5 |
| disaster_relief | verify | 15 | 1.4 | 1.4 | 1.7 |
| disaster_relief | assess | 15 | 0.2 | 0.2 | 0.3 |
| disaster_relief | calculate | 15 | 1.0 | 1.0 | 1.2 |
| disaster_relief | total | 15 | 3.1 | 268.7 | 579.8 |
| land_acquisition | read | 7 | 680.1 | 602.7 | 736.9 |
| land_acquisition | verify | 21 | 2.6 | 2.6 | 3.0 |
| land_acquisition | assess | 21 | 0.1 | 0.1 | 0.1 |
| land_acquisition | calculate | 21 | 0.5 | 0.5 | 0.6 |
| land_acquisition | total | 21 | 3.2 | 204.2 | 687.8 |
| social_welfare | verify | 6 | 0.6 | 0.6 | 0.7 |
| social_welfare | assess | 6 | 0.5 | 0.5 | 0.6 |
| social_welfare | calculate | 6 | 0.6 | 0.6 | 0.7 |
| social_welfare | total | 6 | 1.7 | 1.7 | 1.8 |

## What the stages are

- **read:** extracting the fields of each document image the case has (the time per case is the sum over its
  images). Only cases with an image file are counted; the others were seeded with fields already read.
- **verify:** the scheme's YAML verification checks (name match, duplicates, recorded entries).
- **assess:** the eligibility rules.
- **calculate:** the amount formulas.
- **total:** the sum of the stages measured for that case.

## Limits

- Synthetic documents only: invented cases and clean images, not real records or scans.
- One machine, one run; times vary with the machine, its load and, for a live model, the network.
- Software time only. It excludes human review time, the officer's decision, uploads, queueing and waiting
  for the citizen.
- Reading is measured on the clean image variant only; degraded and hard images take longer and are read
  less reliably (see `docs/EVAL_RESULTS.md`).
