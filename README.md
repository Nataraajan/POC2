# CLAB driver dashboard

Run from this directory:

```sh
python -m pip install -r requirements.txt
python -m streamlit run app.py
```

Use the sidebar to change demand, underwriting, yield, term, default timing,
default rate and seasonality. Switch between Short-Term, Installment and
Combined. Both products keep their assumptions when switching views.

The default-curve chart compares manual assumptions with the existing
historical fit. **Apply historical curve** updates the actual forecast and
shows the revenue change against the current manual assumptions. Switch back
to restore the manual curve. Reset drivers restores the initial assumptions.

Monthly revenue, provision expense and net revenue are visible below the
charts. The Forecast table tab includes the full balance roll-forward,
quarterly totals, a monthly CSV download and an assumptions JSON download.
Quarterly tables exclude incomplete quarters; horizon totals include every month.

## Preserved model and data

`clab_forecast_engine_v2.py`, the historical curve derivation, loan datasets,
and the standalone `vintage_app.py` / `build_triangle.py` pipeline are unchanged.
Formatting and the cached historical loader moved to `dashboard_support.py`.

The forecast uses the existing Short-Term / Installment synthetic loan history.
The separate 2M-loan CreditFresh / MoneyKey analysis can still be launched with
`python -m streamlit run vintage_app.py`. Its products are not automatically
mapped to the forecast products. No new raw-data benchmark is claimed.

The model still starts from an empty book, uses level-payment amortization,
books lifetime expected losses at origination and earns revenue starting the
following month. Charge-offs reduce both gross CLAB and the reserve; they are
not expensed again. There are no prepayments or recoveries. Yield also determines
the contractual repayment schedule.

## Validation

```sh
python -m pip install pytest
python -m pytest tests -q
```

Tests cover default-output equivalence to the original engine, driver effects,
product persistence and combined totals, historical/manual switching, balance
and reserve reconciliation, partial quarters, reset, zero-volume/zero-yield
cases, and standalone vintage startup.

The redesign follows the requested driver-dashboard structure. The referenced
conversation supplied screenshots of the old UI, but no generated mockup image
was recoverable, so this is not a verified pixel-for-pixel reproduction.
