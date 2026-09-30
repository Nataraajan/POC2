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

## One analysis page, two editable curve sources

**Vintage Analysis & Overlay** in `app.py` is the single analysis workflow. It contains the original dataset validation, sample, SQL methodology, censored triangles and derived curves previously shown in the standalone app. `vintage_app.py` is now a landing page linking to `https://cpropel-poc2.streamlit.app/?page=vintage`; it performs no separate analysis. There is no upload mode or separate small-sample overlay experiment.

- **Synthetic vintage** starts from the committed 2M-loan empirical curves. Each segment permits a lifetime-default override and independent default/payoff timing adjustments. Timing 1 preserves the observed conditional curve exactly; an exponent below 1 moves events earlier and above 1 moves events later. The adjusted conditional CDF is `F(age)^timing`. Historical triangles and original curves are never rewritten by overrides.
- **Manual assumptions** constructs conditional curves directly as `min(age / term, 1)^timing`, without using empirical timing. Default rates start at the table's illustrative targets. Initial timing exponents use the table's k values as illustrative manual inputs, **not a fit to the generator's exponential distribution**. Timing 1 means an even distribution over months; smaller is earlier, larger later.

Both modes retain their own settings when switching sources or pages. Changes feed the forecast immediately; reset restores only the selected source. Allowed default rates are 0–99%, and timing exponents are 0.25–4. Both conditional event curves start at zero, are monotone and reach one by term. PD allocates a mutually exclusive default population; `1-PD` allocates a full-payoff population. Payoff means **full loan closure**, not total principal collections; scheduled amortization is modeled separately. The chart compares original synthetic observations with the exact applied forecast curves.

`curve_model.py` owns construction and validation for both sources; `curve_controls.py` provides the shared UI. Source and forecast terms remain fixed at 12/24 months. A new term requires matching history and regenerated curves. The default source is Synthetic vintage. Actual loan products, rates, recoveries, redraws and borrower payment behavior are not calibrated by this POC.

## Forecast assumptions retained

The editable 80/20 brand mix allocates applications and opening gross CLAB within each loan type **before** four independent forecasts are aggregated. History row shares do not impose forecast volume shares. Applications, approval, size, yield, growth and seasonality remain loan-type drivers. The reported June 30, 2026 opening CLAB is $639,083,326. Mapping it to a performing book, its 40/60 loan-type allocation and even surviving-balance age mix are illustrative.

Loans amortize on a level-payment schedule. Default loses the balance still owed (100% LGD, no recoveries); early payoff removes remaining principal after the scheduled payment. Default probability therefore differs from lifetime principal loss. New originations receive an upfront provision; opening reserve covers remaining opening-book losses. Charge-offs reduce gross principal and reserve. Revenue uses beginning principal less that month's charge-offs; new originations earn from the next month. The model does not represent redraws or a real revolving-credit payment ledger.

Click **Prepare Excel model**, then **Download Excel model**. The workbook is generated only on request and reused within your session until exported assumptions change; changed assumptions require a fresh export. Downloading does not rerun the forecast.

The Excel export retains four segment builds, two loan-type aggregations and a main schedule. On **Assumptions**, E6 selects manual (1) or synthetic (2). Segment columns E/F/J/K are CreditFresh Short-Term, MoneyKey Short-Term, CreditFresh Installment and MoneyKey Installment. Rows 52/53/59 hold manual PD/default timing/payoff timing; rows 55/56/57 hold synthetic PD override/default timing/payoff timing. Row 54 preserves original empirical PD, row 58 calculates active PD. Rows 65–101 calculate the applied conditional curves using the same power functions as Python; rows 106–142 retain original synthetic curves. Payoff arrays occupy H/I/M/N. Editing either source's active controls recalculates the corresponding segment and aggregate forecast. Obsolete midpoint and logistic-steepness controls have been removed. Terms must remain aligned with source curves in Excel as well.

The exporter adapts the existing formula template at download time without adding a spreadsheet service to Streamlit. The assumptions JSON download now includes both source settings, original and applied curves, brand share and operating drivers. See `VALIDATION.md` for recalculation checks and limits.

`generate_loan_data.py`, `derive_vintage_curves.py` and `loans.csv` retain the original standalone sigmoid-fitting demonstration. They are legacy examples, not inputs to the current dashboard or segment forecast.

## Reported volume preset (reviewed September 30, 2026)

The base uses the latest available reported quarter, June 30, 2026. All values below are USD. Annual periods and quarterly flows must not be compared without adjusting the period length.

| Period | Ending CLAB | Funded in period | Revenue in period |
|---|---:|---:|---:|
| FY2024 | 480,602,408 | 586,436,066 | 449,730,785 |
| FY2025 | 589,548,106 | 774,263,664 | 589,807,759 |
| Q2 2026 (three months) | 639,083,326 | 243,423,212 | 179,604,747 |

Sources: [FY2024 MD&A](https://cdn.propelholdings.com/web/pdfs/2024PropelQ4MDA.pdf) pp. 25–27; [FY2025 MD&A](https://cdn.propelholdings.com/web/pdfs/2025PropelQ4MDA.pdf) pp. 24–29; [Q2 2026 MD&A](https://cdn.propelholdings.com/web/pdfs/2026PropelQ2MDA.pdf) pp. 14–17 and 18–22. The source module `propel_reference.py` also retains prior-year comparators and links.

Starting funding = Q2 2026 originations / 3 = $81,141,070.67 per month. Same-quarter funding growth = 243,423,212 / 194,394,548 - 1; its compounded monthly equivalent is applied to application growth. This extrapolation is not company guidance or a seasonality estimate. The starting application total remains 125,000 (89,286 Short-Term, 35,714 Installment). Ticket sizes and relative conversions remain illustrative; both conversion rates are multiplied by the same factor to reconcile initial funding to the reported quarterly average. Do not interpret these as actual company application counts or approval rates.

Base restores that growth and conversion. Upside/downside add/subtract 1 percentage point of monthly growth and 3 points of conversion. Reset restores all defaults. Existing sessions retain edited values until Reset.

CLAB YoY growth = 639,083,326 / 520,403,519 - 1. Its extrapolated balance path is a comparison only, never a balancing plug. The UI shows the gap against the cohort model. No claim is made that the synthetic runoff reproduces reported CLAB growth.

The reported company-wide scope includes revolving credit, repeat funding and programs beyond our four hypothetical segments. CLAB is not IFRS net loans receivable. Mapping funded dollars/redraws to new fixed-term cohorts and CLAB to performing principal is a POC approximation. The published revenue yield is not a contractual amortization rate and is not copied into the pricing controls. Credit, payoff, LGD, opening-age and product-share assumptions remain synthetic; the equal-current-balance opening age mix still causes an initial runoff cliff. Actual cohort/payment data is required to calibrate it. The assumptions JSON contains source metadata; Excel receives the same operating inputs through the existing exporter.

## Model assistant and scenarios

Use **Ask AI** at the bottom right to explain the current model or preview changes.
The assistant uses OpenAI (`gpt-5.4-mini` by default); what-if numbers come from the
existing forecast engine. Previews never apply inputs. Conversation history resets
when the model context changes. Questions and summarized model data are sent to
OpenAI only on submission; no loan-level data or API keys are included in prompts.

In Streamlit **Manage app → Settings → Secrets**, set `OPENAI_API_KEY` and optionally
`OPENAI_MODEL`. See `.streamlit/secrets.toml.example` for the format. Never commit
real keys. Missing credentials show a setup message; API failures leave the model
usable. API calls have bounded output, a 30-second request timeout and bounded tool
rounds. Configure provider billing limits for a publicly accessible deployment.

Opening portfolio allocation defaults to 40% Short-Term / 60% Installment. Adjust
its share slider or total; the **40 / 60 preset** restores the split while preserving
the current total. This allocation affects opening balances only. Applications,
new lending and the CreditFresh share remain separate drivers.

**Compare scenarios**, immediately before Reset, shows current, Base, Upside and
Downside results without changing the active scenario. Presets change growth and
approval only, retaining all other current assumptions. The active scenario badge
updates as inputs change. The monthly schedule is now solely on Forecasting;
Model assumptions uses a compact table.
