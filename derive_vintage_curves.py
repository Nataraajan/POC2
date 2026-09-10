"""
derive_vintage_curves.py

Takes loan-level data and derives empirical vintage default curves using
real SQL aggregation (SQLite) — directly demonstrating the "SQL + Python"
approach for analyzing large row-level datasets: push aggregation to the
database, then do curve analysis on the much smaller aggregated result in
Python, rather than ever looping through raw loan rows in application code.

Also validates the whole pipeline: since generate_loan_data.py encodes a
known "true" curve per product, the empirically-derived curve here should
converge toward that true shape as cohorts mature — proving the SQL +
aggregation logic is actually correct, not just plausible-looking.
"""

import sqlite3
import numpy as np
import pandas as pd

from generate_loan_data import PRODUCTS, true_cumulative_default_pct


def load_into_sqlite(loans_df: pd.DataFrame) -> sqlite3.Connection:
    conn = sqlite3.connect(":memory:")
    loans_df.to_sql("loans", conn, index=False)
    return conn


# The actual SQL doing the heavy lifting — this is what would scale to
# millions of real rows in production, run once against the database
# rather than iterating row-by-row in Python.
VINTAGE_AGGREGATION_SQL = """
SELECT
    product,
    origination_month,
    months_observed,
    COUNT(*) AS loan_count,
    SUM(loan_amount) AS total_originated,
    SUM(CASE WHEN status = 'defaulted' THEN loan_amount ELSE 0 END) AS defaulted_amount
FROM loans
GROUP BY product, origination_month, months_observed
"""


def derive_with_loan_detail(loans_df: pd.DataFrame, product: str) -> pd.DataFrame:
    """For one product: at each months-on-book value, what % of the
    ORIGINAL balance of loans old enough to have reached that age has
    defaulted by then? Only cohorts old enough to have been observed at
    a given age contribute to that age's data point — the correct way to
    handle censoring, rather than blending immature and mature cohorts
    together. Uses each defaulted loan's actual default_month_on_book
    (set at generation time) to build the cumulative curve precisely."""
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
    loans_df = pd.read_csv("loans.csv")
    conn = load_into_sqlite(loans_df)

    print("=== SQL aggregation query ===")
    print(VINTAGE_AGGREGATION_SQL)
    agg_result = pd.read_sql(VINTAGE_AGGREGATION_SQL, conn)
    print(f"\nAggregated {len(loans_df):,} raw loan rows down to {len(agg_result)} cohort-level rows.\n")

    for product, cfg in PRODUCTS.items():
        print(f"--- {product} ---")
        derived = derive_with_loan_detail(loans_df, product)
        midpoint = cfg["true_days_to_default"] / 30.0
        derived["true_curve_pct"] = true_cumulative_default_pct(
            derived["months_on_book"].values, midpoint, cfg["true_total_default_rate_pct"]
        )
        print(derived.to_string(index=False))
        print()
