"""
generate_loans.py

Vectorized synthetic loan-level data generator. Designed to scale to
2,000,000+ rows without a per-loan Python loop — the only loop is over the
48 (product x vintage) combinations, which is trivial; everything within
each combination is real numpy array operations.

This step produces default_mob as each loan's TRUE, full-term outcome.
Right-censoring (restricting what's "observable" as of a given date) is
applied later, when building the vintage triangle — NOT here. This file
only needs to produce statistically correct ground-truth outcomes.
"""

import numpy as np
import pandas as pd
from datetime import date
import calendar

RNG = np.random.default_rng(seed=42)

VINTAGES = pd.period_range("2024-07", "2026-06", freq="M")  # 24 months
PRODUCTS = {
    "CreditFresh": {"share": 0.58, "ticket": 1800.0, "term_months": 9, "lifetime_default": 0.20},
    "MoneyKey": {"share": 0.42, "ticket": 700.0, "term_months": 5, "lifetime_default": 0.36},
}
SEASONALITY = {
    1: 0.88, 2: 0.90, 3: 1.00, 4: 1.02, 5: 1.04, 6: 1.08,
    7: 1.00, 8: 1.00, 9: 1.04, 10: 1.06, 11: 1.12, 12: 1.16,
}
CURVE_K = 2.2  # exponential shape parameter


def exponential_cum_curve(lifetime: float, term: int) -> np.ndarray:
    """cum[k] for k=0..term. Hits exactly `lifetime` at k=term, by construction."""
    k = np.arange(0, term + 1)
    return lifetime * (1 - np.exp(-CURVE_K * k / term)) / (1 - np.exp(-CURVE_K))


def generate(total_rows: int = 2_000_000, verbose: bool = True) -> pd.DataFrame:
    # --- Step 1: monthly volume per product, seasonality-adjusted, rescaled to hit total_rows exactly ---
    n_vintages = len(VINTAGES)
    raw_monthly_share = np.array([SEASONALITY[v.month] for v in VINTAGES])
    raw_monthly_share = raw_monthly_share / raw_monthly_share.sum()  # normalize to sum to 1 across vintages
    target_per_vintage = np.round(raw_monthly_share * total_rows).astype(int)
    # Rounding can leave us off by a few rows from the exact total — patch the last vintage.
    target_per_vintage[-1] += total_rows - target_per_vintage.sum()

    all_frames = []
    seq_counters = {}

    for vintage_idx, vintage in enumerate(VINTAGES):
        vintage_total = target_per_vintage[vintage_idx]
        vintage_str = str(vintage)
        yyyymm = vintage.year * 100 + vintage.month
        days_in_month = calendar.monthrange(vintage.year, vintage.month)[1]

        for product_name, cfg in PRODUCTS.items():
            n = int(round(vintage_total * cfg["share"]))
            if n == 0:
                continue

            product_code = 1 if product_name == "CreditFresh" else 2
            seq_start = seq_counters.get((product_code, yyyymm), 0)
            loan_id = product_code * 10**9 + yyyymm * 10**5 + np.arange(seq_start, seq_start + n)
            seq_counters[(product_code, yyyymm)] = seq_start + n

            # Vectorized ticket size, +/-10% uniform noise
            ticket = cfg["ticket"] * RNG.uniform(0.9, 1.1, size=n)

            # Vectorized origination date within the month
            day = RNG.integers(1, days_in_month + 1, size=n)
            origination_date = pd.to_datetime({"year": vintage.year, "month": vintage.month, "day": day})

            # Per-vintage noise on lifetime default rate, then build this vintage's
            # own cumulative curve and derive default_mob for every loan in it at once.
            vintage_lifetime = cfg["lifetime_default"] * RNG.uniform(0.92, 1.08)
            term = cfg["term_months"]
            cum_curve = exponential_cum_curve(vintage_lifetime, term)
            incremental = np.diff(cum_curve, prepend=0.0)  # inc[0..term], sums to vintage_lifetime
            # Categorical distribution over {default at mob 0, 1, ..., term, no default}
            probs = np.append(incremental, 1.0 - vintage_lifetime)
            cum_probs = np.cumsum(probs)
            cum_probs[-1] = 1.0  # guard against float drift

            draws = RNG.uniform(0, 1, size=n)
            outcome_idx = np.searchsorted(cum_probs, draws)  # vectorized — no per-loan loop
            default_mob = np.where(outcome_idx <= term, outcome_idx, -1)

            all_frames.append(pd.DataFrame({
                "loan_id": loan_id,
                "product": product_name,
                "vintage": vintage_str,
                "origination_date": origination_date,
                "ticket": np.round(ticket, 2),
                "term_months": term,
                "default_mob": default_mob,
                "default_flag": (default_mob >= 0).astype(int),
            }))

    df = pd.concat(all_frames, ignore_index=True)

    if verbose:
        print(f"Generated {len(df):,} rows.")
        print(f"loan_id unique: {df['loan_id'].is_unique}")
        print(f"Product mix:\n{(df['product'].value_counts(normalize=True) * 100).round(1)}")
        print(f"Vintages present: {df['vintage'].nunique()}")
        for product_name, cfg in PRODUCTS.items():
            sub = df[df["product"] == product_name]
            term = cfg["term_months"]
            cum_at_term = (sub["default_mob"] == term).sum()  # placeholder, real cum check below
            observed_cum_rate = (sub["default_flag"].sum()) / len(sub)
            print(f"{product_name}: full-sample lifetime default rate = {observed_cum_rate:.3f} "
                  f"(target ~{cfg['lifetime_default']:.2f}, some vintage-noise spread expected)")

    return df


if __name__ == "__main__":
    import json
    import time
    from datetime import datetime
    from pathlib import Path

    DATA_DIR = Path(__file__).resolve().parent / "data"
    DATA_DIR.mkdir(exist_ok=True)
    TOTAL_ROWS = 2_000_000

    t0 = time.time()
    df = generate(total_rows=TOTAL_ROWS)
    elapsed = time.time() - t0
    print(f"\nGenerated in {elapsed:.2f}s")
    print("\nSample rows:")
    print(df.sample(10, random_state=1).to_string(index=False))

    # Full file for build_triangle.py (gitignored — too big to commit), plus a
    # small illustrative sample the app can show without ever loading the full file.
    df.to_parquet(DATA_DIR / "loans.parquet", index=False)
    df.sample(20, random_state=1).sort_values("loan_id").to_csv(DATA_DIR / "loans_sample.csv", index=False)

    # --- Stats capture: real facts from THIS run, displayed by the app ---
    # Same checks as generate()'s verbose output, recomputed here so they can be saved.
    # Written fresh each run, so triangle stats from an older run never linger —
    # build_triangle.py adds its own section afterwards.
    stats = {"generation": {
        "run_at": datetime.now().isoformat(timespec="seconds"),
        "total_rows": len(df),
        "generation_seconds": elapsed,
        "loan_id_unique": bool(df["loan_id"].is_unique),
        "vintages": int(df["vintage"].nunique()),
        "vintage_range": [df["vintage"].min(), df["vintage"].max()],
        "product_mix_pct": {
            product_name: {"observed": float((df["product"] == product_name).mean() * 100),
                           "target": round(cfg["share"] * 100, 4)}
            for product_name, cfg in PRODUCTS.items()
        },
        "default_rate_vs_target": {
            product_name: {"observed": float(df.loc[df["product"] == product_name, "default_flag"].mean()),
                           "target": cfg["lifetime_default"]}
            for product_name, cfg in PRODUCTS.items()
        },
    }}
    (DATA_DIR / "generation_stats.json").write_text(json.dumps(stats, indent=2))
    print(f"\nWrote {DATA_DIR / 'loans.parquet'}, loans_sample.csv, generation_stats.json")
