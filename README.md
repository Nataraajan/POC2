# Driver-Based Revenue Model

This is a synthetic architecture POC, **not a calibrated Propel credit forecast or a representation of the brands' actual product catalogue**. CreditFresh's real product is revolving credit; the fixed terms below are hypothetical model segments for demonstrating consistent history-to-forecast mapping.

Install `requirements.txt` and `pytest`, then run `python -m streamlit run app.py`. Run the complete test suite with `python -m pytest tests -q`.

## One segment definition throughout the pipeline

`segments.py` defines the generator, source terms and forecast mapping:

| Synthetic segment | Term (months) | Target lifetime default | Default shape k | Payoff shape k | History row share |
|---|---:|---:|---:|---:|---:|
| CreditFresh Short-Term | 12 | 20% | 2.2 | 2.5 | 23.2% |
| CreditFresh Installment | 24 | 16% | 1.6 | 1.8 | 34.8% |
| MoneyKey Short-Term | 12 | 36% | 2.8 | 3.0 | 16.8% |
| MoneyKey Installment | 24 | 28% | 2.0 | 2.1 | 25.2% |

All rates, shape parameters, terms and splits are illustrative assumptions. Short-Term rates retain the old brand targets. The two Installment rates and segment timing parameters demonstrate independent behavior, without claiming an empirical basis for their chosen values. History retains the old 58/42 brand sampling mix, split 40/60 by loan type within each brand. Ticket centers remain $1,800/$700 by brand, with uniform +/-10% noise; these weight the timing experiment, rather than calibrating forecast loan sizes.

Each loan has an explicit brand, loan type, term and composite segment key in `product`. Defaults follow a normalized exponential cumulative distribution reaching the segment target at its term. Vintage target rates receive uniform +/-8% relative noise, clipped to [0,1]. Non-defaulting loans receive a payoff month from a separate normalized exponential timing distribution. Default and payoff are mutually exclusive, occur in months 1 through term, and exhaust outcomes by term. Generation uses a local seed (default 42); identical inputs reproduce identical data.

## Derivation and forecast handoff

`python precompute.py` generates 2,000,000 loans spanning July 2023-June 2026 and rebuilds **all** committed samples, statistics, triangles and curves from that same run. The full `data/loans.parquet` remains ignored. Use `--rows` and `--seed` for experiments; committed validation expects the default 2M run.

SQL aggregates each segment and vintage separately. Triangle cells beyond the June 2026 cutoff or segment term are absent, not zero. Forecast curves use only fully mature vintages: 24 monthly cohorts for 12-month segments and 12 for 24-month segments. Default and payoff curves use the same loans and original-ticket denominator at every age. Recent cohorts remain visible in the censored triangle but do not set forecast timing.

`overlay_curve.csv` and `payment_curves.json` contain the same cumulative default observations. Each segment's empirical default and payoff arrays feed its forecast directly, with flat tails after term. There is no sigmoid fitting, brand pooling, term stretching or cross-segment fallback. Missing mature data raises an error. If a mature sample has no events of one type, its timing is unidentifiable: a flagged term-end fallback is used with zero mass in historical mode. A manual PD change can give that fallback nonzero mass.

Manual mode edits four segment PDs independently while retaining their timing arrays. Historical mode uses observed synthetic PDs. Source and forecast terms must match; the UI fixes Short-Term at 12 and Installment at 24 months. A new term requires matching history and regenerated curves. Live demos and overlay previews use the same estimator and exact mapping.

## Forecast assumptions retained

The editable 80/20 brand mix allocates applications and opening gross CLAB within each loan type **before** four independent forecasts are aggregated. History row shares do not impose forecast volume shares. Applications, approval, size, yield, growth and seasonality remain loan-type drivers. The user-supplied $639M opening book, illustrative 40/60 loan-type allocation and default even surviving-balance age mix remain unchanged.

Loans amortize on a level-payment schedule. Default loses the balance still owed (100% LGD, no recoveries); early payoff removes remaining principal after the scheduled payment. Default probability therefore differs from lifetime principal loss. New originations receive an upfront provision; opening reserve covers remaining opening-book losses. Charge-offs reduce gross principal and reserve. Revenue uses beginning principal less that month's charge-offs; new originations earn from the next month. The model does not represent redraws or a real revolving-credit payment ledger.

The Excel export has four independent segment risk inputs and empirical arrays, four segment builds, two loan-type aggregations and a main schedule. The exporter adapts the existing formula template at download time. Terms must remain aligned with source curves in Excel as well. See `VALIDATION.md` for checks performed and limitations; previous recalculation claims do not automatically apply to a newly generated workbook.

`generate_loan_data.py`, `derive_vintage_curves.py` and `loans.csv` retain the original standalone sigmoid-fitting demonstration. They are legacy examples, not inputs to the current dashboard or segment forecast.
