"""
clab_forecast_engine.py

Rolls forward Ending CLAB (the operating loan book — "stock of credit
originated or facilitated," not an IFRS balance sheet figure) month by
month, per product, over a forecast horizon:

    Ending CLAB(t) = Beginning CLAB(t) + Originations(t) - Charge-offs(t)

This is structurally the same roll-forward identity as the SaaS revenue
model's ARR bridge (Ending ARR = Beginning ARR + New ARR + Expansion -
Contraction - Churn) — a balance that grows from new business and shrinks
from losses, tracked cohort by cohort so the balance stays genuinely
continuous rather than being recomputed from scratch each period.

Funnel driving Originations, per month:
    Applications(t) = base_applications x seasonal_multiplier(t)
    Originations($, t) = Applications(t) x Approval Rate x Avg Loan Size

Charge-offs are cohort-based: each month's originations become a vintage
that ages forward, charging off according to a default curve (see
vintage_analysis.py for how that curve gets derived from historical data
rather than just assumed).

Revenue:
    Revenue(t) = Ending CLAB(t) x (Annual Yield / 12)

Design principles carried over from the rest of this portfolio:
- No randomization in the forecasting math itself — deterministic given
  inputs and a default curve, whether that curve is assumed or derived
  from data.
- Seasonality is an explicit, user-set 12-month multiplier pattern, not
  inferred — same convention as the SaaS model's PodConfig.seasonality_pattern.
- Deliberately simplified for this POC: CLAB shrinks only from defaults,
  not a separate paydown/amortization mechanic. Real CLAB also shrinks
  from normal loan paydowns as customers repay on schedule — flagged, not
  modeled, to keep this POC focused specifically on the funnel-to-balance
  mechanism and the vintage-curve overlay that were asked for.
"""

import numpy as np
import pandas as pd

CURVE_STEEPNESS = 0.55  # same curve family as the vintage analysis module


def cumulative_default_pct(months_on_book, midpoint_months, total_rate_pct):
    raw = 1.0 / (1.0 + np.exp(-CURVE_STEEPNESS * (months_on_book - midpoint_months)))
    raw_at_zero = 1.0 / (1.0 + np.exp(CURVE_STEEPNESS * midpoint_months))
    normalized = (raw - raw_at_zero) / (1.0 - raw_at_zero)
    return total_rate_pct * normalized


def forecast_clab(monthly_applications_base: float, seasonality_pattern: list,
                   approval_rate_pct: float, avg_loan_size: float, annual_yield_pct: float,
                   midpoint_months: float, total_default_rate_pct: float,
                   horizon_months: int = 24, starting_clab: float = 0.0) -> pd.DataFrame:
    """
    seasonality_pattern: exactly 12 multipliers (month 1..12), cycles
    automatically for horizons beyond 12 months — same convention as the
    SaaS model.
    """
    if len(seasonality_pattern) != 12:
        raise ValueError(f"seasonality_pattern must have exactly 12 values, got {len(seasonality_pattern)}")

    rows = []
    cohort_original_balance = {}  # origination_month -> $ originated that month
    ending_clab_prev = starting_clab

    for month in range(1, horizon_months + 1):
        seasonal_mult = seasonality_pattern[(month - 1) % 12]
        applications_this_month = monthly_applications_base * seasonal_mult
        originations_this_month = applications_this_month * (approval_rate_pct / 100.0) * avg_loan_size
        cohort_original_balance[month] = originations_this_month

        charge_offs_this_month = 0.0
        for origination_month, original_balance in cohort_original_balance.items():
            age = month - origination_month
            cum_now = cumulative_default_pct(np.array([age]), midpoint_months, total_default_rate_pct)[0]
            cum_prev = cumulative_default_pct(np.array([age - 1]), midpoint_months, total_default_rate_pct)[0] if age > 0 else 0.0
            incremental_pct = (cum_now - cum_prev) / 100.0
            charge_offs_this_month += original_balance * incremental_pct

        beginning_clab = ending_clab_prev
        ending_clab = beginning_clab + originations_this_month - charge_offs_this_month
        revenue_this_month = ending_clab * (annual_yield_pct / 100.0 / 12.0)

        rows.append({
            "month": month,
            "applications": applications_this_month,
            "originations": originations_this_month,
            "beginning_clab": beginning_clab,
            "charge_offs": charge_offs_this_month,
            "ending_clab": ending_clab,
            "revenue": revenue_this_month,
        })
        ending_clab_prev = ending_clab

    return pd.DataFrame(rows)


def aggregate_to_quarterly(monthly_df: pd.DataFrame) -> pd.DataFrame:
    """Rolls monthly forecast output up to quarterly, matching how Propel
    itself reports externally (per the CLAB table researched separately) —
    same monthly-internally/quarterly-for-reporting split as the SaaS model."""
    df = monthly_df.copy()
    df["quarter"] = ((df["month"] - 1) // 3) + 1

    quarterly = df.groupby("quarter").agg(
        applications=("applications", "sum"),
        originations=("originations", "sum"),
        charge_offs=("charge_offs", "sum"),
        revenue=("revenue", "sum"),
        ending_clab=("ending_clab", "last"),  # a balance — take period-END, don't sum
    ).reset_index()
    quarterly["beginning_clab"] = df.groupby("quarter")["beginning_clab"].first().values
    return quarterly
