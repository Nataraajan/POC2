# Validation — 11 September 2026

**17 tests passed** after the opening-portfolio, navigation and Excel revision.

- Original empty-book forecast matches a fixture captured from commit 0c82eb7.
- Opening cohorts at MOB 0, MOB 3 and an even age mix repay fully and exhaust
  their loss reserve, at both zero and 100% annual yield.
- Existing-book reserve is not rebooked as provision expense.
- Independent first-month survival, principal and charge-off calculations agree.
- Combined opening gross CLAB is $639M and month-one revenue is positive.
- Gross CLAB, reserve and net revenue reconcile monthly.
- Product switching preserves assumptions and combined totals add correctly.
- Historical/manual curve switching restores manual assumptions.
- Growth presets, reset, partial quarters, term-one loans and invalid ages tested.
- The separate vintage app starts without a Streamlit exception.
- All four navigation pages preserve edited drivers and the selected curve.

The exported historical-case Excel model was independently recalculated with
Artifact Tool: 2,757 financial values reconcile to the Python engine (maximum
dollar difference 0.000000462). Editing applications doubles originations;
switching to manual credit inputs changes the applied curve. Formula error
scan found none. Workbook formatting was visually checked using saved cell
values and styles after the primary renderer returned blank images. Native
desktop Excel was not available for an additional application-level check.

Default combined month 1, using the stated illustrative split and age mix:
revenue $38.60M; new provisions $2.46M; net revenue $36.14M.
These are model outputs, not reported company revenue. Original demo annual
yields of 100% and 55% remain inputs and must be replaced if inappropriate.

Browser QA checks the driver panel, six cards, both charts, visible monthly
table, historical-curve action and downloadable schedule. The local service
was restarted after the engine signature change to clear the old imported
module from the previous server session.

Environment: Python 3.11, Streamlit 1.63.0, pandas 3.0.5, NumPy 2.4.6,
Plotly 7.0.0, PyArrow 25.0.1, pytest 9.1.1.

Annual KPI checks verify 12-month originations totals and suppress partial-year results. Browser review confirmed separated KPI cards and curve legend below the plot. Curve hover labels explicitly name product, source, applied/comparison status, MOB and percentage. Forecast engine and Excel formulas are unchanged by this presentation update.
