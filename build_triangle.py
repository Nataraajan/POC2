"""
build_triangle.py

Extraction -> Computation -> Output, made explicit and visible:

  1. EXTRACTION: load the 2M-row loans.parquet.
  2. COMPUTATION: real SQL (SQLite) aggregation into a vintage triangle,
     WITH proper right-censoring applied at the observation date — a
     vintage only contributes a data point at a given mob if it's
     actually old enough to have been observed that far as of 2026-06-30.
     Skipping this would make every vintage look fully mature, which is
     wrong and would make the resulting curve artificially clean.
  3. OUTPUT: overlay_curve.csv, derived from the CENSORED triangle (never
     from raw default_flag on the full file) — the only file the
     forecast model imports.
"""

import sqlite3
import pandas as pd

OBSERVATION_DATE = pd.Period("2026-06", freq="M")  # "today" — end of the last vintage month
TERMS = {"CreditFresh": 9, "MoneyKey": 5}


def months_elapsed(vintage_str: str) -> int:
    vintage_period = pd.Period(vintage_str, freq="M")
    return (OBSERVATION_DATE.year - vintage_period.year) * 12 + (OBSERVATION_DATE.month - vintage_period.month)


# --- Step 1: EXTRACTION ---
def load_loans(path: str = "data/loans.parquet") -> pd.DataFrame:
    return pd.read_parquet(path)


# --- Step 2: COMPUTATION (real SQL) ---
RAW_AGGREGATION_SQL = """
SELECT
    product,
    vintage,
    default_mob AS mob,
    COUNT(*) AS loans_defaulted_at_mob,
    SUM(ticket) AS dollars_defaulted_at_mob
FROM loans
WHERE default_mob >= 0
GROUP BY product, vintage, default_mob
"""

ORIGINATIONS_SQL = """
SELECT product, vintage, COUNT(*) AS loan_count, SUM(ticket) AS originations
FROM loans
GROUP BY product, vintage
"""


SQL_COLUMNS = ["product", "vintage", "default_mob", "ticket"]  # the only columns the two queries read


def build_triangle(loans_df: pd.DataFrame) -> pd.DataFrame:
    conn = sqlite3.connect(":memory:")
    # Only the columns the SQL reads go into SQLite — identical query results, and copying rows
    # into the database is most of this function's cost.
    loans_df[SQL_COLUMNS].to_sql("loans", conn, index=False)

    defaults_by_mob = pd.read_sql(RAW_AGGREGATION_SQL, conn)
    originations_by_vintage = pd.read_sql(ORIGINATIONS_SQL, conn)
    # One dict lookup per triangle cell, instead of filtering the aggregate table for every cell.
    nco_by_cell = {(product, vintage, mob): dollars for product, vintage, mob, dollars in
                   defaults_by_mob[["product", "vintage", "mob", "dollars_defaulted_at_mob"]].itertuples(index=False)}

    rows = []
    for product, vintage, originations in originations_by_vintage[["product", "vintage", "originations"]].itertuples(index=False):
        term = TERMS[product]
        max_observable_mob = min(term, months_elapsed(vintage))  # <-- the censoring rule

        for mob in range(0, term + 1):
            if mob > max_observable_mob:
                continue  # not yet observable — leave this cell out of the triangle entirely

            rows.append({
                "product": product, "vintage": vintage, "mob": mob,
                "originations": originations, "nco": nco_by_cell.get((product, vintage, mob), 0.0),
            })

    triangle = pd.DataFrame(rows)
    triangle["nco_rate"] = triangle["nco"] / triangle["originations"]
    triangle["observed_cum"] = triangle.groupby(["product", "vintage"])["nco_rate"].cumsum()
    return triangle


# --- Step 3: OUTPUT — overlay curve, built from the CENSORED triangle only ---
def build_overlay_curve(triangle: pd.DataFrame) -> pd.DataFrame:
    """For each (product, mob), pool ONLY the vintages old enough to have
    actually reached that mob — never average incomplete/censored vintages
    in with mature ones, and never include a mob a vintage hasn't reached."""
    rows = []
    for product in triangle["product"].unique():
        product_triangle = triangle[triangle["product"] == product]
        term = TERMS[product]
        for mob in range(0, term + 1):
            eligible = product_triangle[product_triangle["mob"] == mob]  # already censored — only eligible rows exist here at all
            if len(eligible) == 0:
                continue
            pooled_nco = eligible["nco"].sum()
            pooled_originations = eligible["originations"].sum()
            incremental_rate_at_mob = pooled_nco / pooled_originations if pooled_originations > 0 else 0.0
            rows.append({"product": product, "mob": mob, "incremental_rate": incremental_rate_at_mob})

    overlay = pd.DataFrame(rows)
    overlay["cum_default"] = overlay.groupby("product")["incremental_rate"].cumsum()
    return overlay[["product", "mob", "cum_default"]]


if __name__ == "__main__":
    import json
    import time
    from datetime import datetime
    from pathlib import Path

    DATA_DIR = Path(__file__).resolve().parent / "data"

    t0 = time.time()
    loans_df = load_loans(DATA_DIR / "loans.parquet")
    load_seconds = time.time() - t0
    print(f"Loaded {len(loans_df):,} rows from loans.parquet in {load_seconds:.2f}s")

    t1 = time.time()
    triangle = build_triangle(loans_df)
    triangle_seconds = time.time() - t1
    print(f"Built triangle ({len(triangle)} rows) in {triangle_seconds:.2f}s")

    overlay = build_overlay_curve(triangle)

    triangle.to_parquet(DATA_DIR / "vintage_triangle.parquet", index=False)
    overlay.to_csv(DATA_DIR / "overlay_curve.csv", index=False)

    # --- Stats capture: real facts from THIS run, added to generate_loans.py's stats ---
    stats_path = DATA_DIR / "generation_stats.json"
    stats = json.loads(stats_path.read_text()) if stats_path.exists() else {}
    # Every vintage has a mob-0 row (always observable), so the triangle's product x vintage
    # pairs are all of them; any cell of the full term grid that's absent was censored out.
    full_grid_cells = sum(TERMS[product] + 1 for product in
                          triangle[["product", "vintage"]].drop_duplicates()["product"])
    stats["triangle"] = {
        "run_at": datetime.now().isoformat(timespec="seconds"),
        "rows_loaded": len(loans_df),
        "load_seconds": load_seconds,
        "triangle_build_seconds": triangle_seconds,
        "observation_date": str(OBSERVATION_DATE),
        "triangle_cells": len(triangle),
        "cells_excluded_by_censoring": full_grid_cells - len(triangle),
        "sql_queries": {
            "defaults_by_mob": RAW_AGGREGATION_SQL.strip(),
            "originations_by_vintage": ORIGINATIONS_SQL.strip(),
        },
    }
    stats_path.write_text(json.dumps(stats, indent=2))
    print(f"Wrote vintage_triangle.parquet, overlay_curve.csv, and triangle stats to {stats_path.name}")

    print(f"\noverlay_curve.csv: {len(overlay)} rows")
    print(overlay.to_string(index=False))

    print("\n--- Censoring sanity check ---")
    for product in TERMS:
        recent_vintage = "2026-05"
        old_vintage = "2024-08"
        recent_rows = triangle[(triangle["product"] == product) & (triangle["vintage"] == recent_vintage)]
        old_rows = triangle[(triangle["product"] == product) & (triangle["vintage"] == old_vintage)]
        print(f"{product}: vintage {recent_vintage} has {len(recent_rows)} mob rows observable "
              f"(should be very few — barely aged); vintage {old_vintage} has {len(old_rows)} mob rows "
              f"(should be the full term+1, fully matured)")
