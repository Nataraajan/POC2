# LendSight — CLAB driver forecast

```sh
python -m pip install -r requirements.txt
python -m streamlit run app.py
```

The dashboard follows the supplied LendSight reference: navy navigation,
five driver groups, six monthly KPI cards, revenue and curve charts side by
side, and a visible monthly forecast schedule. All displayed controls operate
on the forecast. Search, notifications and unsupported modules from the image
are omitted rather than presented as inactive controls.

## Opening portfolio

The initial combined opening CLAB is **$639M at end-Q2**, supplied by the user.
It is treated as gross performing principal. The initial allocation of 40%
Short-Term ($255.6M) / 60% Installment ($383.4M) is **an assumption**; use the
product selector to edit either balance. It is not a reported product split.

MOB composition is unknown. The default assumes equal current balances across
each active MOB from zero through term minus one. A single opening cohort age
is also supported. Existing loans run off through principal payments and
charge-offs, and earn interest from the first forecast month. Their opening
reserve equals remaining expected losses and is not booked as a new expense.

Changing credit assumptions recomputes the modeled opening reserve. This is
a planning scenario, not an accounting catch-up calculation against an actual
booked allowance. Actual cohort balances, contractual yields and the actual
booked reserve should replace assumptions when available.

New originations still earn starting the following month. Their lifetime loss
provision is booked at origination. This preserves the original timing model;
the earlier zero-revenue month arose because the original forecast had no
opening book. Setting opening balances to zero reproduces that behavior.

## Drivers and outputs

The top panel controls applications, monthly growth, seasonality, approval,
loan size, term, annual yield, manual/historical curves, default-rate stress,
and opening portfolio assumptions. Yield retains its original dual role as
contractual rate and revenue yield. Stress scales default probability, not
loss severity. Prepayments and recoveries are not modeled.

Base/Upside/Downside are explicitly illustrative presets for growth, approval,
and stress. Other inputs are retained. Reset restores the starting assumptions.
The six KPI cards show Year 1 and Year 2 totals (months 1–12 and 13–24), with year-end snapshots for gross and net CLAB. PLL replaces charge-offs in the headline cards. Incomplete years show no annual value. Detail month selects the monthly runoff explanation. The monthly
schedule remains visible; the reconciliation expander adds full balance detail
and complete quarterly totals. Sidebar navigation opens Forecasting, Monthly
schedule, Vintage analysis and Model assumptions while retaining drivers.

The Excel model download contains editable assumptions, a monthly financial
statement and both product cohort builds with auditable formulas. Blue text
marks inputs, black text formulas and green text cross-sheet links. Amounts
are shown in thousands, with balance checks and a 36-month calculation build;
selected-horizon totals match the app. Excel recalculates on opening. Historical
fit parameters are imported from Python; the resulting default curves and all
forecast cash flows are calculated in Excel. CSV and assumptions JSON remain available.

The active default curve is labeled APPLIED; historical mode also reports its
revenue/provision impact against manual assumptions with other drivers fixed.
Revenue can decline because the opening portfolio runs off faster than new
originations replace it. The dashboard shows this monthly balance bridge.

Historical fitting and censoring are unchanged. The forecast uses its original
Short-Term / Installment synthetic history. The separate CreditFresh / MoneyKey
2M-loan pipeline remains available via `streamlit run vintage_app.py`; its
products are not mapped to the forecast. No new 2M-row benchmark is claimed.

## Validation

```sh
python -m pip install pytest
python -m pytest tests -q
```

See VALIDATION.md for checks and assumptions. The model remains a planning
prototype; the supplied opening balance does not turn synthetic loan history
or demo yields into company actuals.

The executive cards lead with revenue, PLL and net revenue, with annual changes and the user-supplied 45–50% PLL/revenue benchmark. This benchmark is informational, not a forced forecast input. The monthly summary has months across columns and amounts in millions. Historical fitting uses derive_vintage_curves.py through dashboard_support.py: cumulative defaults are weighted by original loan amount, not actual written-off principal.

Vintage overlay page incorporates the updated Propel_tool vintage app and default-rate override generator. Generate 100,000 synthetic loans, explicitly map CreditFresh/MoneyKey source curves to model products, and preview/apply fitted parameters. Fits use equally weighted MOB points, a fixed sigmoid shape and PD bounded to 0–99%; raw points remain visible for comparison. Stress applies after fitting. Applying updates historical-mode calculations and Excel parameters; it does not change manual assumptions. Reset or Restore original historical fits removes the mapping. The original 2M precomputed results remain separate.
