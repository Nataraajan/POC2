"""
derive_vintage_curves.py

Takes loan-level data and derives empirical vintage default curves using
real SQL aggregation (SQLite) — directly demonstrating the "SQL + Python"
approach for analyzing large row-level datasets: push aggregation to the
database, then do curve analysis on the much smaller aggregated result in
Python, rather than ever looping through raw loan rows in application code.

Three steps:
1. SQL builds the vintage triangle — one row per product x origination
   cohort x month-on-book the cohort has actually been observed at, with
   $ originated and cumulative $ defaulted by that age.
2. Python pools the triangle into one curve per product: at each age, total
   defaulted / total originated across every cohort old enough to have
   reached it.
3. Python fits the forecast engine's default-curve shape to that pooled
   curve, producing the two inputs the forecast needs (total default rate,
   timing midpoint) — both from the data, nothing borrowed from the answer key.

Also validates the whole pipeline: since generate_loan_data.py encodes a
known "true" curve per product, the fitted parameters here should land
close to the true ones — proving the SQL + aggregation + fit logic is
actually correct, not just plausible-looking.
"""

import sqlite3

import numpy as np
import pandas as pd

from clab_forecast_engine_v2 import cumulative_default_pct
from generate_loan_data import LOANS_CSV, PRODUCTS, true_cumulative_default_pct


def load_into_sqlite(loans_df: pd.DataFrame) -> sqlite3.Connection:
    conn = sqlite3.connect(":memory:")
    loans_df.to_sql("loans", conn, index=False)
    return conn


# The actual SQL doing the heavy lifting — this is what would scale to
# millions of real rows in production, run once against the database
# rather than iterating row-by-row in Python.
#
# Censoring is handled by the JOIN: a cohort only gets a row for the ages
# it has actually been observed at (months_on_book <= months_observed). A
# 4-month-old cohort contributes nothing to the month-8 data point, instead
# of wrongly counting as "0% defaulted by month 8".
VINTAGE_TRIANGLE_SQL = """
WITH RECURSIVE ages(months_on_book) AS (
    SELECT 0
    UNION ALL
    SELECT months_on_book + 1 FROM ages
    WHERE months_on_book < (SELECT MAX(months_observed) FROM loans)
)
SELECT
    l.product,
    l.origination_month,
    a.months_on_book,
    COUNT(*) AS loan_count,
    SUM(l.loan_amount) AS originated,
    SUM(CASE WHEN l.status = 'defaulted' AND l.default_month_on_book <= a.months_on_book
             THEN l.loan_amount ELSE 0 END) AS cum_defaulted
FROM loans l
JOIN ages a ON a.months_on_book <= l.months_observed
GROUP BY l.product, l.origination_month, a.months_on_book
ORDER BY l.product, l.origination_month, a.months_on_book
"""


def build_vintage_triangle(conn: sqlite3.Connection) -> pd.DataFrame:
    triangle = pd.read_sql(VINTAGE_TRIANGLE_SQL, conn)
    triangle["cum_default_pct"] = triangle["cum_defaulted"] / triangle["originated"] * 100
    return triangle


def pooled_default_curve(triangle: pd.DataFrame, product: str) -> pd.DataFrame:
    """One curve per product: at each months-on-book value, what % of the
    ORIGINAL balance of loans old enough to have reached that age has
    defaulted by then? Pools $ across cohorts (not an average of cohort
    percentages), so bigger cohorts carry proportionally more weight."""
    pooled = (triangle[triangle["product"] == product]
              .groupby("months_on_book")
              .agg(cohorts=("origination_month", "count"),
                   eligible_balance=("originated", "sum"),
                   defaulted=("cum_defaulted", "sum"))
              .reset_index())
    pooled["cumulative_default_pct"] = pooled["defaulted"] / pooled["eligible_balance"] * 100
    return pooled


def fit_default_curve(pooled: pd.DataFrame) -> dict:
    """Fits the forecast engine's curve shape (steepness fixed at
    CURVE_STEEPNESS) to a pooled empirical curve, returning both inputs the
    forecast needs.

    Weighted least squares, weighted by eligible balance — so the mature,
    heavily-populated early ages drive the fit and the thin tail (one or two
    cohorts at the oldest ages) can't swing it. Deterministic, no solver
    dependency: for each candidate midpoint on a fine grid, the best total
    default rate has an exact closed-form answer, so just take the midpoint
    with the lowest error.
    """
    ages = pooled["months_on_book"].to_numpy(dtype=float)
    observed = pooled["cumulative_default_pct"].to_numpy()
    weights = pooled["eligible_balance"].to_numpy()

    best = None
    for midpoint in np.arange(0.1, 24.0 + 1e-9, 0.01):
        shape = cumulative_default_pct(ages, midpoint, 1.0)  # curve per 1% of total rate
        total = np.sum(weights * observed * shape) / np.sum(weights * shape ** 2)
        sse = np.sum(weights * (observed - total * shape) ** 2)
        if best is None or sse < best["sse"]:
            best = {"sse": sse, "midpoint_months": float(midpoint), "total_default_rate_pct": float(total)}

    return {"total_default_rate_pct": best["total_default_rate_pct"],
            "midpoint_months": best["midpoint_months"],
            "days_to_default": best["midpoint_months"] * 30.0}


def derive_with_loan_detail(loans_df: pd.DataFrame, product: str) -> pd.DataFrame:
    """Independent brute-force recomputation of the pooled curve in pandas,
    straight from raw loan rows. Not used by the app — kept only to
    cross-check that the SQL triangle + pooling produces identical numbers."""
    product_df = loans_df[loans_df["product"] == product]

    rows = []
    max_age = product_df["months_observed"].max()

    for age in range(0, int(max_age) + 1):
        eligible_cohorts = product_df[product_df["months_observed"] >= age]
        if len(eligible_cohorts) == 0:
            continue

        eligible_balance = eligible_cohorts["loan_amount"].sum()
        defaulted_by_age = eligible_cohorts[
            (eligible_cohorts["status"] == "defaulted") &
            (eligible_cohorts["default_month_on_book"] <= age)
        ]["loan_amount"].sum()

        cum_default_pct = (defaulted_by_age / eligible_balance * 100) if eligible_balance > 0 else 0.0
        rows.append({
            "months_on_book": age,
            "eligible_balance": eligible_balance,
            "cumulative_default_pct": cum_default_pct,
        })

    return pd.DataFrame(rows)


if __name__ == "__main__":
    loans_df = pd.read_csv(LOANS_CSV)
    conn = load_into_sqlite(loans_df)

    print("=== SQL vintage triangle query ===")
    print(VINTAGE_TRIANGLE_SQL)
    triangle = build_vintage_triangle(conn)
    print(f"Aggregated {len(loans_df):,} raw loan rows down to {len(triangle)} cohort x age rows.\n")

    for product, cfg in PRODUCTS.items():
        print(f"--- {product} ---")
        pooled = pooled_default_curve(triangle, product)

        brute_force = derive_with_loan_detail(loans_df, product)
        max_diff = np.abs(pooled["cumulative_default_pct"].to_numpy() - brute_force["cumulative_default_pct"].to_numpy()).max()
        print(f"Cross-check vs. pandas brute force: max difference {max_diff:.2e} percentage points")

        fit = fit_default_curve(pooled)
        print(f"Fitted: total default rate {fit['total_default_rate_pct']:.2f}%, days to default {fit['days_to_default']:.0f}")
        print(f"True:   total default rate {cfg['true_total_default_rate_pct']:.2f}%, days to default {cfg['true_days_to_default']}")

        pooled["fitted_curve_pct"] = cumulative_default_pct(
            pooled["months_on_book"].to_numpy(dtype=float), fit["midpoint_months"], fit["total_default_rate_pct"])
        pooled["true_curve_pct"] = true_cumulative_default_pct(
            pooled["months_on_book"].to_numpy(dtype=float),
            cfg["true_days_to_default"] / 30.0, cfg["true_total_default_rate_pct"])
        print(pooled[["months_on_book", "cohorts", "eligible_balance", "cumulative_default_pct",
                      "fitted_curve_pct", "true_curve_pct"]].round(3).to_string(index=False))
        print()
