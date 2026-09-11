"""
clab_forecast_engine_v2.py

Revenue driver flow: Applications -> Approval Rate -> Originations -> CLAB
(gross + reserve + net) -> Yield -> Revenue, with provisioning driven by a
vintage default curve. Replaces clab_forecast_engine.py.

Loans repay on a level-payment schedule over the product term, so each
month's originations become a vintage whose balance runs off through
principal repayments as well as charge-offs. For a vintage at age a
(months on book), per $1 originated:
    d(a) = cumulative % of the vintage's loans that have defaulted by age a
    B(a) = scheduled principal still outstanding (0 once a >= term)

    Performing balance(a) = (1 - d(a)) x B(a)
    Charge-offs(a)        = [d(a) - d(a-1)] x B(a-1)
                            (written off at the balance still owed)
    Principal repaid(a)   = (1 - d(a)) x [B(a-1) - B(a)]

Two upgrades from the v1 engine:

1. PROVISIONING MECHANIC (IFRS 9 / CECL-style), not a direct charge-off model.
   Real lenders book an expected-loss provision at origination, immediately
   hitting the P&L — they don't wait for losses to actually emerge. This
   splits CLAB into three tracked balances:

     Gross CLAB   = Beginning + Originations - Principal Repaid - Charge-offs
     Reserve      = Beginning + New Provisions - Charge-offs
     Net CLAB     = Gross CLAB - Reserve

   New Provisions are booked the month a loan originates, sized at the
   vintage's full lifetime expected loss: sum over ages of
   [d(a) - d(a-1)] x B(a-1) — the default curve applied to the balance
   still owed at each age. Because loans amortize, that is below the
   headline default rate (a loan that defaults in month 6 has already
   repaid part of its principal), and it is exactly what the vintage's
   charge-offs add up to over its life — so each vintage's reserve drains
   to zero by the end of its term instead of leaving a stranded balance.
   Charge-offs draw down the reserve: the P&L already took the hit at
   origination, so a charge-off is not a second P&L expense, just the
   reserve and the gross book both shrinking together.

     Revenue      = (Beginning Gross CLAB - Charge-offs) x Annual Yield / 12
                    (interest paid by loans that make this month's payment;
                     new originations earn nothing in their first month)
     Net Revenue  = Revenue - New Provisions

2. FULL VECTORIZATION VIA CONVOLUTION. Every per-$1 flow above depends only
   on a vintage's age, so each calendar-month total, summed across all
   aging vintages, is a discrete convolution of the origination series with
   that flow's age curve — charge_offs = convolve(originations, charge-off
   curve), and likewise for principal repaid. That replaces the per-month,
   per-cohort Python loop with numpy.convolve calls plus cumulative sums for
   the running balances. Same output as the loop, far fewer operations.

Design principles carried over from the rest of this portfolio:
- No randomization in the forecasting math — deterministic given inputs
  and a default curve, whether that curve is assumed or fitted to data.
- Seasonality is an explicit, user-set 12-month multiplier pattern, not
  inferred — same convention as the SaaS model's PodConfig.seasonality_pattern.
- The forecast starts from an empty book: a starting balance would need its
  own vintage history to run off correctly, so there is no opening-balance
  input rather than one that would just sit on the books unamortized.
"""

import numpy as np
import pandas as pd

CURVE_STEEPNESS = 0.55  # same curve family as the vintage analysis module


def cumulative_default_pct(months_on_book, midpoint_months, total_rate_pct):
    """Cumulative default % by age. Accepts any ages (scalar or array, not just
    integers) — the vintage module fits this same curve to historical data."""
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


def vintage_curves(midpoint_months: float, total_default_rate_pct: float, term_months: int,
                   annual_yield_pct: float, max_age: int) -> dict:
    """Per-$1 flow curves for one vintage, indexed by age 0..max_age."""
    ages = np.arange(0, max_age + 1)
    d = cumulative_default_pct(ages, midpoint_months, total_default_rate_pct) / 100.0
    B = remaining_principal_fraction(ages, term_months, annual_yield_pct)
    d_prev = np.concatenate([[0.0], d[:-1]])
    B_prev = np.concatenate([[1.0], B[:-1]])
    charge_off = (d - d_prev) * B_prev
    principal = (1 - d) * (B_prev - B)
    charge_off[0] = principal[0] = 0.0  # nothing happens in the month a loan is originated
    return {"charge_off": charge_off, "principal": principal}


def lifetime_expected_loss(midpoint_months: float, total_default_rate_pct: float, term_months: int,
                           annual_yield_pct: float) -> float:
    """Lifetime $ loss per $1 originated — the sum of the vintage's charge-off
    curve over its whole life. B(a-1) is 0 past the term, so ages beyond
    term + 1 contribute nothing."""
    return float(vintage_curves(midpoint_months, total_default_rate_pct, term_months,
                                annual_yield_pct, term_months + 1)["charge_off"].sum())


def forecast_clab_v2(monthly_applications_base: float, seasonality_pattern: list,
                      approval_rate_pct: float, avg_loan_size: float, annual_yield_pct: float,
                      midpoint_months: float, total_default_rate_pct: float,
                      term_months: int, horizon_months: int = 24) -> pd.DataFrame:
    """
    seasonality_pattern: exactly 12 multipliers (month 1..12), cycles
    automatically for horizons beyond 12 months.

    annual_yield_pct doubles as the contractual rate driving the
    amortization schedule — the interest borrowers pay IS the revenue.
    """
    if len(seasonality_pattern) != 12:
        raise ValueError(f"seasonality_pattern must have exactly 12 values, got {len(seasonality_pattern)}")
    if term_months < 1:
        raise ValueError(f"term_months must be at least 1, got {term_months}")

    months = np.arange(1, horizon_months + 1)

    # --- Vectorized originations series, no loop ---
    seasonal_mults = np.array([seasonality_pattern[(m - 1) % 12] for m in months])
    applications = monthly_applications_base * seasonal_mults
    originations = applications * (approval_rate_pct / 100.0) * avg_loan_size

    # --- Provisioning: lifetime expected loss, booked in full the month of origination ---
    new_provisions = originations * lifetime_expected_loss(midpoint_months, total_default_rate_pct,
                                                           term_months, annual_yield_pct)

    # --- Charge-offs and repayments via convolution, not a nested loop ---
    curves = vintage_curves(midpoint_months, total_default_rate_pct, term_months, annual_yield_pct, horizon_months)
    charge_offs = np.convolve(originations, curves["charge_off"])[:horizon_months]  # trim convolution tail to horizon
    principal_repaid = np.convolve(originations, curves["principal"])[:horizon_months]

    # --- Running balances via cumulative sums, not a sequential loop ---
    gross_clab = np.cumsum(originations) - np.cumsum(principal_repaid) - np.cumsum(charge_offs)
    reserve = np.cumsum(new_provisions) - np.cumsum(charge_offs)
    net_clab = gross_clab - reserve

    beginning_gross_clab = np.concatenate([[0.0], gross_clab[:-1]])
    beginning_reserve = np.concatenate([[0.0], reserve[:-1]])

    revenue = (beginning_gross_clab - charge_offs) * (annual_yield_pct / 100.0 / 12.0)
    net_revenue = revenue - new_provisions

    return pd.DataFrame({
        "month": months, "applications": applications, "originations": originations,
        "beginning_gross_clab": beginning_gross_clab, "principal_repaid": principal_repaid,
        "charge_offs": charge_offs, "ending_gross_clab": gross_clab,
        "new_provisions": new_provisions, "beginning_reserve": beginning_reserve,
        "ending_reserve": reserve, "net_clab": net_clab,
        "revenue": revenue, "net_revenue": net_revenue,
    })


def aggregate_to_quarterly(monthly_df: pd.DataFrame) -> pd.DataFrame:
    """Rolls monthly forecast output up to quarterly, matching how Propel
    itself reports externally — monthly internally, quarterly for reporting.

    Flows are summed; balances take the period's first (beginning) or last
    (ending) month, never a sum. Full quarters only: a trailing partial
    quarter is dropped rather than shown as a 1-month "quarter" next to
    3-month ones. Its months still appear in the monthly data."""
    df = monthly_df.copy()
    df["quarter"] = ((df["month"] - 1) // 3) + 1

    quarterly = df.groupby("quarter").agg(
        months=("month", "count"),
        applications=("applications", "sum"),
        originations=("originations", "sum"),
        beginning_gross_clab=("beginning_gross_clab", "first"),
        principal_repaid=("principal_repaid", "sum"),
        charge_offs=("charge_offs", "sum"),
        ending_gross_clab=("ending_gross_clab", "last"),
        new_provisions=("new_provisions", "sum"),
        beginning_reserve=("beginning_reserve", "first"),
        ending_reserve=("ending_reserve", "last"),
        net_clab=("net_clab", "last"),
        revenue=("revenue", "sum"),
        net_revenue=("net_revenue", "sum"),
    ).reset_index()
    return quarterly[quarterly["months"] == 3].drop(columns="months").reset_index(drop=True)
