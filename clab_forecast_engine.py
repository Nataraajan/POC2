"""
clab_forecast_engine.py

Rolls forward Ending CLAB (the operating loan book — "stock of credit
originated or facilitated," not an IFRS balance sheet figure) month by
month, per product, over a forecast horizon:

    Ending CLAB(t) = Beginning CLAB(t) + Originations(t)
                     - Principal Repaid(t) - Charge-offs(t)

This is structurally the same roll-forward identity as the SaaS revenue
model's ARR bridge (Ending ARR = Beginning ARR + New ARR + Expansion -
Contraction - Churn) — a balance that grows from new business and shrinks
from runoff and losses, tracked cohort by cohort so the balance stays
genuinely continuous rather than being recomputed from scratch each period.

Funnel driving Originations, per month:
    Applications(t) = base_applications x seasonal_multiplier(t)
    Originations($, t) = Applications(t) x Approval Rate x Avg Loan Size

Each month's originations become a vintage that ages forward. For a
vintage at age a (months on book):
    d(a) = cumulative % of the vintage's loans that have defaulted by age a
           (the default curve — see derive_vintage_curves.py for how it gets
           fitted to historical data rather than just assumed)
    B(a) = scheduled principal still outstanding per $1 originated, from a
           level-payment amortization over the loan term (0 once a >= term)

    Performing balance(a) = Original x (1 - d(a)) x B(a)
    Charge-offs(a)        = Original x [d(a) - d(a-1)] x B(a-1)
                            (a defaulting loan is written off at the balance
                             it still owed — the payment it missed never came)
    Principal repaid(a)   = Original x (1 - d(a)) x [B(a-1) - B(a)]

These three always reconcile: prior balance - charge-offs - principal
repaid = new balance, exactly. A loan that has fully repaid can't default,
so if the term is shorter than the default curve, part of the headline
default rate never turns into dollar losses.

Revenue is the interest portion of this month's scheduled payments, from
loans that actually make them:
    Revenue(t) = (Beginning CLAB(t) - Charge-offs(t)) x (Annual Yield / 12)
New originations earn nothing in their first month (first payment is due
the following month).

Design principles carried over from the rest of this portfolio:
- No randomization in the forecasting math itself — deterministic given
  inputs and a default curve, whether that curve is assumed or fitted
  to data.
- Seasonality is an explicit, user-set 12-month multiplier pattern, not
  inferred — same convention as the SaaS model's PodConfig.seasonality_pattern.
"""

import numpy as np
import pandas as pd

CURVE_STEEPNESS = 0.55  # same curve family as the vintage analysis module


def cumulative_default_pct(months_on_book, midpoint_months, total_rate_pct):
    raw = 1.0 / (1.0 + np.exp(-CURVE_STEEPNESS * (months_on_book - midpoint_months)))
    raw_at_zero = 1.0 / (1.0 + np.exp(CURVE_STEEPNESS * midpoint_months))
    normalized = (raw - raw_at_zero) / (1.0 - raw_at_zero)
    return total_rate_pct * normalized


def remaining_principal_fraction(months_on_book, term_months: int, annual_rate_pct: float):
    """Scheduled principal outstanding per $1 originated, for a level-payment
    (fully amortizing) loan — the standard installment-loan schedule. Hits
    exactly 0 at the end of the term and stays there."""
    a = np.clip(np.asarray(months_on_book, dtype=float), 0, term_months)
    r = annual_rate_pct / 100.0 / 12.0
    if r == 0:
        return 1.0 - a / term_months
    growth_full = (1 + r) ** term_months
    return (growth_full - (1 + r) ** a) / (growth_full - 1)


def forecast_clab(monthly_applications_base: float, seasonality_pattern: list,
                   approval_rate_pct: float, avg_loan_size: float, annual_yield_pct: float,
                   midpoint_months: float, total_default_rate_pct: float,
                   term_months: int, horizon_months: int = 24) -> pd.DataFrame:
    """
    seasonality_pattern: exactly 12 multipliers (month 1..12), cycles
    automatically for horizons beyond 12 months — same convention as the
    SaaS model.

    annual_yield_pct doubles as the contractual rate driving the
    amortization schedule — the interest borrowers pay IS the revenue.
    """
    if len(seasonality_pattern) != 12:
        raise ValueError(f"seasonality_pattern must have exactly 12 values, got {len(seasonality_pattern)}")
    if term_months < 1:
        raise ValueError(f"term_months must be at least 1, got {term_months}")

    # Per-$1 vintage curves by age, computed once and reused for every vintage
    ages = np.arange(0, horizon_months + 1)
    d = cumulative_default_pct(ages, midpoint_months, total_default_rate_pct) / 100.0
    B = remaining_principal_fraction(ages, term_months, annual_yield_pct)
    monthly_rate = annual_yield_pct / 100.0 / 12.0

    rows = []
    cohort_original_balance = {}  # origination_month -> $ originated that month
    ending_clab_prev = 0.0

    for month in range(1, horizon_months + 1):
        seasonal_mult = seasonality_pattern[(month - 1) % 12]
        applications_this_month = monthly_applications_base * seasonal_mult
        originations_this_month = applications_this_month * (approval_rate_pct / 100.0) * avg_loan_size

        charge_offs_this_month = 0.0
        principal_repaid_this_month = 0.0
        for origination_month, original_balance in cohort_original_balance.items():
            a = month - origination_month  # >= 1: this month's cohort is added after the loop
            charge_offs_this_month += original_balance * (d[a] - d[a - 1]) * B[a - 1]
            principal_repaid_this_month += original_balance * (1 - d[a]) * (B[a - 1] - B[a])
        cohort_original_balance[month] = originations_this_month

        beginning_clab = ending_clab_prev
        ending_clab = beginning_clab + originations_this_month - principal_repaid_this_month - charge_offs_this_month
        revenue_this_month = (beginning_clab - charge_offs_this_month) * monthly_rate

        rows.append({
            "month": month,
            "applications": applications_this_month,
            "originations": originations_this_month,
            "beginning_clab": beginning_clab,
            "principal_repaid": principal_repaid_this_month,
            "charge_offs": charge_offs_this_month,
            "ending_clab": ending_clab,
            "revenue": revenue_this_month,
        })
        ending_clab_prev = ending_clab

    return pd.DataFrame(rows)


def aggregate_to_quarterly(monthly_df: pd.DataFrame) -> pd.DataFrame:
    """Rolls monthly forecast output up to quarterly, matching how Propel
    itself reports externally (per the CLAB table researched separately) —
    same monthly-internally/quarterly-for-reporting split as the SaaS model.

    Full quarters only: a trailing partial quarter (e.g. month 25 of a
    25-month horizon) is dropped rather than shown as a 1-month "quarter"
    next to 3-month ones — same full-periods-only rule as the SaaS model's
    annual Summary sheet. Its months still appear in the monthly data."""
    df = monthly_df.copy()
    df["quarter"] = ((df["month"] - 1) // 3) + 1

    quarterly = df.groupby("quarter").agg(
        months=("month", "count"),
        applications=("applications", "sum"),
        originations=("originations", "sum"),
        principal_repaid=("principal_repaid", "sum"),
        charge_offs=("charge_offs", "sum"),
        revenue=("revenue", "sum"),
        beginning_clab=("beginning_clab", "first"),  # a balance — take period-START, don't sum
        ending_clab=("ending_clab", "last"),  # a balance — take period-END, don't sum
    ).reset_index()
    return quarterly[quarterly["months"] == 3].drop(columns="months").reset_index(drop=True)
