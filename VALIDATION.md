# Validation — 11 September 2026

22 tests pass, including original engine fixtures, opening-book reconciliation,
product and loan-type aggregation, historical/manual switching, live vintage
handoff, zero/100% product mix and mix sensitivity. The lending engine remains
unchanged; four independent segment calls precede aggregation.

Excel recalculation: 6,692 financial values reconcile to Python with maximum
dollar difference 0.000000239. Changes to applications and product credit inputs
recalculate correctly. An 80% to 65% CreditFresh mix change under the illustrative
historical case changes 24-month revenue from $509.29M to $497.05M and PLL from
$185.14M to $211.98M. Formula error scan is clear.

Browser verification also confirms that editing the mix changes combined
revenue and PLL. Workbook values/styles are reviewed with a read-only fallback
renderer because Artifact Tool previews are blank in this runtime. Native
desktop Excel was not tested.
