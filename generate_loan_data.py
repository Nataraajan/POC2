"""
generate_loan_data.py

Generates synthetic loan-level data across 2 products, over 24 months of
originations, with realistic vintage-curve behavior baked in via a hidden
"true" hazard curve per product — so the analysis pipeline (SQL aggregation
+ empirical curve derivation) can be checked against a known ground truth,
not just eyeballed for plausibility.

Design note on randomization: this generator uses randomness deliberately
(with a fixed seed for reproducibility) to produce realistic individual
loan outcomes. This is different from the modeling/analysis principle used
elsewhere (deterministic, no randomization) — that principle applies to
how results are COMPUTED from given data, not to how synthetic test data
is fabricated in the first place. Real lending data wouldn't need this
step at all; this only exists to have something realistic to analyze.

Critical realism detail — right-censoring: "today" is the end of month 24.
A loan originated in month 20 has only been observed for 4 months, so it
can only show as defaulted if its true default timing falls within that
4-month window. A loan that WOULD default in month 8 of its life simply
hasn't gotten there yet if it's only 4 months old — it shows as "current",
not "will never default". This is real vintage-curve methodology, not a
simplification: ignoring censoring is a classic mistake that makes recent
cohorts look artificially healthy.
"""

import numpy as np
import pandas as pd

RNG = np.random.default_rng(seed=42)  # fixed seed — reproducible synthetic data
HORIZON_MONTHS = 24  # "today" = end of month 24
CURVE_STEEPNESS = 0.55  # same shape family as the assumption-based POC


def true_cumulative_default_pct(months_on_book, midpoint_months, total_rate_pct):
    raw = 1.0 / (1.0 + np.exp(-CURVE_STEEPNESS * (months_on_book - midpoint_months)))
    raw_at_zero = 1.0 / (1.0 + np.exp(CURVE_STEEPNESS * midpoint_months))
    normalized = (raw - raw_at_zero) / (1.0 - raw_at_zero)
    return total_rate_pct * normalized


# ---------------------------------------------------------------------
# Two products, deliberately different risk/return profiles — so the
# derived curves visibly differ by product, not just by random noise.
# ---------------------------------------------------------------------
PRODUCTS = {
    "Short-Term": {
        "avg_loan_size": 1500, "loan_size_spread": 400, "annual_rate_pct": 36.0,
        "true_total_default_rate_pct": 12.0, "true_days_to_default": 60,
        "monthly_originations_base": 900, "monthly_growth": 8,
    },
    "Installment": {
        "avg_loan_size": 4000, "loan_size_spread": 900, "annual_rate_pct": 18.0,
        "true_total_default_rate_pct": 6.0, "true_days_to_default": 150,
        "monthly_originations_base": 500, "monthly_growth": 5,
    },
}


def sample_default_month_on_book(midpoint_months, total_rate_pct, max_months=48):
    """Inverse-transform sampling from the true cumulative default curve.
    Returns None if this particular loan never defaults (drawn as a
    survivor past total_rate_pct), otherwise the month-on-book it would
    default AT — which may fall beyond the observation window (censored)."""
    if RNG.uniform(0, 100) > total_rate_pct:
        return None  # this loan is a lifetime survivor — never defaults
    target_cum_pct = RNG.uniform(0, total_rate_pct)
    grid = np.arange(0, max_months, 0.5)
    curve = true_cumulative_default_pct(grid, midpoint_months, total_rate_pct)
    idx = np.searchsorted(curve, target_cum_pct)
    return grid[min(idx, len(grid) - 1)]


def generate():
    rows = []
    loan_id = 1

    for product_name, cfg in PRODUCTS.items():
        midpoint = cfg["true_days_to_default"] / 30.0

        for origination_month in range(1, HORIZON_MONTHS + 1):
            age_now = HORIZON_MONTHS - origination_month  # months this cohort has actually been observed
            n_originations = int(cfg["monthly_originations_base"] + cfg["monthly_growth"] * origination_month)

            for _ in range(n_originations):
                loan_amount = max(200, RNG.normal(cfg["avg_loan_size"], cfg["loan_size_spread"]))
                true_default_month = sample_default_month_on_book(
                    midpoint, cfg["true_total_default_rate_pct"]
                )

                if true_default_month is not None and true_default_month <= age_now:
                    status = "defaulted"
                    default_month_on_book = round(true_default_month, 1)
                else:
                    status = "current"  # either a true survivor, OR would default later than we've observed yet
                    default_month_on_book = None

                rows.append({
                    "loan_id": loan_id,
                    "product": product_name,
                    "origination_month": origination_month,  # 1-24
                    "loan_amount": round(loan_amount, 2),
                    "annual_rate_pct": cfg["annual_rate_pct"],
                    "status": status,
                    "default_month_on_book": default_month_on_book,
                    "months_observed": age_now,
                })
                loan_id += 1

    df = pd.DataFrame(rows)
    return df


if __name__ == "__main__":
    df = generate()
    df.to_csv("loans.csv", index=False)
    print(f"Generated {len(df):,} loan records across {df['product'].nunique()} products.")
    print(df.groupby("product").agg(
        loans=("loan_id", "count"),
        total_originated=("loan_amount", "sum"),
        defaulted=("status", lambda s: (s == "defaulted").sum()),
    ))
