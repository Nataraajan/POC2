# Driver-Based Revenue Model

Run `python -m pip install -r requirements.txt`, then `python -m streamlit run app.py`.

The forecast calculates four segments: CreditFresh Short-Term, CreditFresh
Installment, MoneyKey Short-Term and MoneyKey Installment. The editable 80/20
product mix allocates opening CLAB and new applications before calculation.
Each product has its own default probability and timing curve. Loan size,
approval, yield, term, growth and seasonality remain loan-type drivers.
Changing product mix therefore changes PLL and revenue when risk differs.

The $639M opening book is user supplied. Its 40/60 loan-type split and even
current-balance age distribution are illustrative. Manual product default
rates start at 20% and 36%, based on synthetic generator assumptions.
Historical mode fits the precomputed CreditFresh/MoneyKey curves, with fixed
sigmoid steepness and equally weighted observed ages. Live vintage experiments
can replace those product fits. Both loan types within a product use that
product's curve. These are not calibrated company credit forecasts.

Lifetime losses are balance-weighted and provisioned on new origination.
Opening reserve covers the remaining expected loss of the opening book.
Charge-offs reduce gross principal and reserve. Revenue uses performing
beginning principal less that month's charge-offs; new loans earn next month.
LGD is 100%; no recoveries, prepayments or existing-reserve catch-up P&L.
Product PD is controlled directly, capped at 99%. PLL/revenue 45–50% is a user-supplied
benchmark, not a forced result.

The Excel download includes four auditable segment builds, two loan-type
aggregations and a main financial schedule. Product share and credit inputs
are on Assumptions; formulas recalculate the mix before losses and revenue.
The shared stress adjustment has been removed; app and Excel use product PD directly. Financial values display in thousands. Horizon totals
use the chosen forecast length; a 36-month build remains available.

Vintage analysis retains the original generation, SQL, sample rows, censored
triangles and live demo. Vintage overlay previews and applies product curves.
The main schedule shows months horizontally and product revenue separately.

Run `python -m pytest tests -q` for engine, UI and integration checks.
