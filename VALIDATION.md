# Validation - 30 September 2026

The full suite contains 61 tests. Run `python -m pytest tests -q`.

Full run after adding the reported-volume preset: **61 passed**, zero failures (Python 3.11, Streamlit 1.64.0). `git diff --check` is clean. The default synthetic forecast now uses observed PDs; manual curves intentionally use an independent power family.

## Verified behavior

- Original empty-book engine regression remains unchanged; the lending engine itself is unchanged.
- Exact four-segment identity, 12/24-month terms, row counts, unique IDs, reproducible seeded generation, segment shares and outcome bounds.
- Mutually exclusive default/payoff outcomes and distinct timing arrays for each segment.
- SQL triangle censoring by observation month and segment term; forecast default/payoff curves independently reconstructed from original loan-ticket dollars.
- Future outcomes in immature cohorts do not affect forecast curves. Missing mature data fails explicitly. Zero-event timing uses a disclosed term-end fallback.
- Each curve changes only its matching brand/loan-type forecast. Missing segment curves and mismatched terms fail instead of silently using another curve.
- Opening-book runoff, gross/reserve reconciliation, loan-type and brand aggregation, zero/100% brand mixes and payoff sensitivity.
- Streamlit startup, synthetic/manual switching, separate source settings, driver persistence, scenarios, consolidated navigation and fixed terms. Synthetic adjustments leave the original triangle unchanged; resetting one source preserves the other source's settings.
- Manual curve construction succeeds without any empirical data. Identity synthetic timing exactly preserves every original curve point. Timing and PD boundaries preserve monotonicity, mutually exclusive outcomes, nonnegative repayments, opening-book runoff and reserve reconciliation. Invalid controls fail explicitly.
- Exported Excel XML has four separate credit inputs and default/payoff arrays. Each segment's formulas reference the matching inputs, cached revenue matches Python, and aggregate revenue reconciles. Excel formulas return #N/A if a term is edited away from its source term.

## Rebuilt evidence

`python precompute.py` completed with seed 42 and 2,000,000 loans over 36 monthly vintages (July 2023-June 2026). It produced 1,980 observed triangle cells and 76 segment/age default points. All small committed samples, statistics and curves now come from that same run. The full loan parquet is excluded from Git.

Line of Credit segments have 24 fully mature vintages at the June 2026 cutoff; Installment segments have 12. Both default and payoff curves use the same mature loans and original-ticket weights. The plotted overlay and applied empirical default arrays agree to floating-point precision.

## Assumptions and limits

The four fixed-term segments, default targets (20%, 16%, 36%, 28%), exponential shape parameters and historical 40/60 loan-type sampling split are hypothetical POC assumptions, **not calibrated Propel credit assumptions or actual branded product terms**. See README for every parameter and the distinction between historical sampling and forecast volume allocation.

## Workbook recalculation and visual checks

The exported workbook was imported and recalculated using Artifact Tool, independently of the Python-produced cell caches. Six cases were exercised by changing actual workbook cells: synthetic baseline; synthetic PD/default/payoff adjustments; manual baseline; manual adjustments with a 65% brand share and Line of Credit-only view; zero default with a 100% brand share; and 99% default with later defaults, earlier payoffs and MoneyKey Installment-only exposure.

Across all six cases, 11 financial rows × 24 months = **1,584 recalculated values** matched Python. Maximum absolute difference was below $0.000001. The scan found no unexpected formula errors. The test scripts are `tests/export_workbook_cases.py` (argument: temporary output directory) and `tests/recalculate_workbook.mjs` (same directory; requires `@oai/artifact-tool` in the development environment). These are development checks, not additional Streamlit dependencies.

Changed assumption controls, calculated curve arrays and the affected forecast schedule were rendered and visually inspected. Clipped segment headers and obsolete midpoint commentary were corrected. The consolidated page and forecast/export controls were reviewed in a local browser as well as AppTest.

Desktop Excel and LibreOffice were not available for native recalculation verification. The evidence above verifies the exported formulas in Artifact Tool; it does not claim testing in those native applications. Financial assumptions remain illustrative.

The export lifecycle test confirms no workbook generation on initial load or input changes, reuse after preparation, and invalidation/rebuild after assumptions change. Workbook calculations are unchanged.

Reported-volume validation checks the exact $639,083,326 opening balance, 125,000 starting applications, initial funding of $243,423,212 / 3, and the 12-month funding ratio of $243,423,212 / $194,394,548. Scenario/reset checks use compounded growth. The reported CLAB growth comparison does not override model balances. Public data covers FY2024, FY2025 and Q2 2026, with primary-source URLs in `propel_reference.py` and README. No credit or repayment calibration is claimed.


### Warm-rerun hot path (September 30, 2026)

Forecast outputs, curve definitions, and Excel formulas are unchanged. Plotly is
imported only when a chart is requested; Excel export imports only after Prepare
Excel model is clicked. The forecast cache hashes driver inputs (including horizon),
brand mix, resolved curves, and source settings; it stores only model data.
Manual comparison and each chart default off. The schedule precedes forecast
charts. Drivers and dependent outputs share a Streamlit fragment; vintage rendering
remains confined to its navigation section and uses precomputed data only.

Local Streamlit AppTest, eight identical warm full reruns after one initial load:
median before 254.8 ms, after 132.0 ms (48.2% reduction). These are local server-side
measurements, not Streamlit Cloud wake-up or browser/network timing. Both runs use
the default forecast, 24 months, with the after version's optional charts and
manual comparison off. No page splitting or raw loan-file loading was introduced.

### Synthetic month shifts (September 30, 2026)

Synthetic default and full-payoff timing now use integer month shifts, default 0,
range -12 to +12. Negative shifts collect events no earlier than MOB 1; positive
shifts retain events through MOB 36. PD and raw history are unchanged. Amortization
is unchanged: events after full scheduled repayment have no dollar exposure.
Manual curve-shape exponents remain separate. Existing sessions reset old synthetic
multipliers to zero shifts and preserve PD.

86 Python tests pass, including exact zero-shift identity, event-by-event shift
checks, probability conservation, invalid-shift rejection and balance/reserve
reconciliation. Independent workbook recalculation passes synthetic base/adjusted,
manual base/adjusted, zero-PD and high-PD cases (including +12/-12 shifts). Across
1,584 financial cells, maximum absolute difference from Python is below $0.000002;
no spreadsheet formula errors were found.
