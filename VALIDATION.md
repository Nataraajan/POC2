# Validation - 30 September 2026

The full suite contains 38 tests. Run `python -m pytest tests -q`.

Final full run: **38 passed in 85.54 seconds**, zero failures (Python 3.11, pytest 9.1.1, Streamlit 1.64.0, pandas 3.0.6, NumPy 2.4.6). git diff --check is clean.

## Verified behavior

- Original empty-book engine regression remains unchanged; the lending engine itself is unchanged.
- Exact four-segment identity, 12/24-month terms, row counts, unique IDs, reproducible seeded generation, segment shares and outcome bounds.
- Mutually exclusive default/payoff outcomes and distinct timing arrays for each segment.
- SQL triangle censoring by observation month and segment term; forecast default/payoff curves independently reconstructed from original loan-ticket dollars.
- Future outcomes in immature cohorts do not affect forecast curves. Missing mature data fails explicitly. Zero-event timing uses a disclosed term-end fallback.
- Each curve changes only its matching brand/loan-type forecast. Missing segment curves and mismatched terms fail instead of silently using another curve.
- Opening-book runoff, gross/reserve reconciliation, loan-type and brand aggregation, zero/100% brand mixes and payoff sensitivity.
- Streamlit startup, manual/historical switching, driver persistence, scenarios, navigation, fixed source terms, live-demo handoff and overlay application.
- Exported Excel XML has four separate credit inputs and default/payoff arrays. Each segment's formulas reference the matching inputs, cached revenue matches Python, and aggregate revenue reconciles. Excel formulas return #N/A if a term is edited away from its source term.

## Rebuilt evidence

`python precompute.py` completed with seed 42 and 2,000,000 loans over 36 monthly vintages (July 2023-June 2026). It produced 1,980 observed triangle cells and 76 segment/age default points. All small committed samples, statistics and curves now come from that same run. The full loan parquet is excluded from Git.

Short-Term segments have 24 fully mature vintages at the June 2026 cutoff; Installment segments have 12. Both default and payoff curves use the same mature loans and original-ticket weights. The plotted overlay and applied empirical default arrays agree to floating-point precision.

## Assumptions and limits

The four fixed-term segments, default targets (20%, 16%, 36%, 28%), exponential shape parameters and historical 40/60 loan-type sampling split are hypothetical POC assumptions, **not calibrated Propel credit assumptions or actual branded product terms**. See README for every parameter and the distinction between historical sampling and forecast volume allocation.

The complete workbook has not been recalculated in desktop Excel or LibreOffice for this change, and visual workbook rendering was not performed. Export tests verify formula wiring and Python-produced caches; they do not certify every formula's recalculated result. The prior 6,692-value Excel recalculation claim applied to an earlier model and is not carried forward. UI tests use Streamlit AppTest, not a visual browser review.
