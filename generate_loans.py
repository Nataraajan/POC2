"""
generate_loans.py

Vectorized synthetic loan-level data generator. Designed to scale to
2,000,000+ rows without a per-loan Python loop — the only loop is over the
144 (segment x vintage) combinations, which is trivial; everything within
each combination is real numpy array operations.

This step produces default_mob as each loan's TRUE, full-term outcome.
Right-censoring (restricting what's "observable" as of a given date) is
applied later, when building the vintage triangle — NOT here. This file
produces illustrative synthetic outcomes, not calibrated company assumptions.
"""

import numpy as np
import pandas as pd
import calendar

from segments import SEGMENTS as PRODUCTS

VINTAGES = pd.period_range("2023-07", "2026-06", freq="M")
SEASONALITY = {
    1: 0.88, 2: 0.90, 3: 1.00, 4: 1.02, 5: 1.04, 6: 1.08,
    7: 1.00, 8: 1.00, 9: 1.04, 10: 1.06, 11: 1.12, 12: 1.16,
}
CURVE_K = 2.2  # exponential shape parameter


def exponential_cum_curve(lifetime: float, term: int, shape: float = CURVE_K) -> np.ndarray:
    """cum[k] for k=0..term. Hits exactly `lifetime` at k=term, by construction."""
    k = np.arange(0, term + 1)
    return lifetime * (1 - np.exp(-shape * k / term)) / (1 - np.exp(-shape))


PAYOFF_DECAY_K = 2.5  # default helper shape; each segment supplies its own value


def payoff_timing_distribution(term: int, shape: float = PAYOFF_DECAY_K) -> np.ndarray:
    """Probability distribution over payoff month (1..term) for loans that
    DON'T default — front-loaded (peaks early, decays toward term), using a
    chosen illustrative decay shape. This is a normalized
    timing distribution, not a rate: by construction it always sums to
    exactly 1.0, since every non-defaulting loan pays off SOMEWHERE by
    month `term` (that's the definition of not defaulting)."""
    months = np.arange(1, term + 1)
    weights = np.exp(-shape * months / term)
    return weights / weights.sum()


def generate(total_rows: int = 2_000_000, verbose: bool = True,
             lifetime_default_overrides: dict = None, seed: int = 42) -> pd.DataFrame:
    """Generate full-term outcomes. Overrides use exact segment names; seed is per run."""
    if not isinstance(total_rows, int) or total_rows <= 0:
        raise ValueError("total_rows must be a positive integer")
    RNG = np.random.default_rng(seed)
    overrides = lifetime_default_overrides or {}
    if set(overrides) - set(PRODUCTS):
        raise ValueError("Default overrides must name an exact brand/loan-type segment")
    if any(not np.isfinite(v) or not 0 <= v <= 1 for v in overrides.values()):
        raise ValueError("Default overrides must lie between zero and one")
    # --- Step 1: monthly volume per product, seasonality-adjusted, rescaled to hit total_rows exactly ---
    raw_monthly_share = np.array([SEASONALITY[v.month] for v in VINTAGES])
    raw_monthly_share = raw_monthly_share / raw_monthly_share.sum()  # normalize to sum to 1 across vintages
    target_per_vintage = np.floor(raw_monthly_share * total_rows).astype(int)
    # Rounding can leave us off by a few rows from the exact total — patch the last vintage.
    target_per_vintage[-1] += total_rows - target_per_vintage.sum()

    all_frames = []

    for vintage_idx, vintage in enumerate(VINTAGES):
        vintage_total = target_per_vintage[vintage_idx]
        vintage_str = str(vintage)
        days_in_month = calendar.monthrange(vintage.year, vintage.month)[1]

        counts = np.floor([vintage_total * c["share"] for c in PRODUCTS.values()]).astype(int)
        counts[-1] += vintage_total - counts.sum()
        for product_idx, (product_name, cfg) in enumerate(PRODUCTS.items()):
            n = counts[product_idx]
            if n == 0:
                continue
            # Global sequential IDs cannot collide even in multi-million-row runs.
            seq_start = sum(len(frame) for frame in all_frames)
            loan_id = np.arange(seq_start + 1, seq_start + n + 1)

            # Vectorized ticket size, +/-10% uniform noise
            ticket = cfg["ticket"] * RNG.uniform(0.9, 1.1, size=n)

            # Vectorized origination date within the month
            day = RNG.integers(1, days_in_month + 1, size=n)
            origination_date = pd.to_datetime({"year": vintage.year, "month": vintage.month, "day": day})

            # Per-vintage noise on lifetime default rate, then build this vintage's
            # own cumulative curve and derive default_mob for every loan in it at once.
            vintage_lifetime = min(1.0, overrides.get(product_name, cfg["lifetime_default"]) * RNG.uniform(0.92, 1.08))
            term = cfg["term_months"]
            cum_curve = exponential_cum_curve(vintage_lifetime, term, cfg["default_k"])
            incremental = np.diff(cum_curve, prepend=0.0)  # inc[0..term], sums to vintage_lifetime
            # Categorical distribution over {default at mob 0, 1, ..., term, no default}
            probs = np.append(incremental, 1.0 - vintage_lifetime)
            cum_probs = np.cumsum(probs)
            cum_probs[-1] = 1.0  # guard against float drift

            draws = RNG.uniform(0, 1, size=n)
            outcome_idx = np.searchsorted(cum_probs, draws)  # vectorized — no per-loan loop
            default_mob = np.where(outcome_idx <= term, outcome_idx, -1)
            default_flag = (default_mob >= 0).astype(int)

            # For every loan that did NOT default, draw its payoff month from
            # the front-loaded payoff-timing distribution — vectorized the
            # same way as the default draw above, no per-loan loop.
            payoff_dist = payoff_timing_distribution(term, cfg["payoff_k"])
            payoff_cum_probs = np.cumsum(payoff_dist)
            payoff_cum_probs[-1] = 1.0  # guard against float drift
            payoff_draws = RNG.uniform(0, 1, size=n)
            payoff_month_idx = np.searchsorted(payoff_cum_probs, payoff_draws) + 1  # months are 1-indexed
            # Only applies to non-defaulting loans — defaulted loans get -1 (mutually exclusive with default_mob).
            payoff_mob = np.where(default_flag == 0, payoff_month_idx, -1)

            all_frames.append(pd.DataFrame({
                "loan_id": loan_id,
                "product": product_name,
                "brand": cfg["brand"],
                "loan_type": cfg["loan_type"],
                "vintage": vintage_str,
                "origination_date": origination_date,
                "ticket": np.round(ticket, 2),
                "term_months": term,
                "default_mob": default_mob,
                "default_flag": default_flag,
                "payoff_mob": payoff_mob,
                "payoff_flag": (payoff_mob >= 0).astype(int),
            }))

    df = pd.concat(all_frames, ignore_index=True)

    if verbose:
        print(f"Generated {len(df):,} rows.")
        print(f"loan_id unique: {df['loan_id'].is_unique}")
        print(f"Product mix:\n{(df['product'].value_counts(normalize=True) * 100).round(1)}")
        print(f"Vintages present: {df['vintage'].nunique()}")
        for product_name, cfg in PRODUCTS.items():
            sub = df[df["product"] == product_name]
            observed_cum_rate = sub["default_flag"].mean()
            target_used = overrides.get(product_name, cfg["lifetime_default"])
            print(f"{product_name}: full-sample lifetime default rate = {observed_cum_rate:.3f} "
                  f"(target ~{target_used:.2f}, some vintage-noise spread expected)")

    return df


if __name__ == "__main__":
    import os
    import time

    os.makedirs("data", exist_ok=True)

    t0 = time.time()
    df = generate(total_rows=2_000_000)
    elapsed = time.time() - t0
    print(f"\nGenerated 2,000,000 rows in {elapsed:.2f}s")

    df.to_parquet("data/loans.parquet", index=False)
    df.sample(20, random_state=1).sort_values("vintage").to_csv("data/loans_sample.csv", index=False)
    print("Saved data/loans.parquet and data/loans_sample.csv")

    size_mb = os.path.getsize("data/loans.parquet") / (1024 * 1024)
    print(f"loans.parquet size: {size_mb:.1f} MB")
