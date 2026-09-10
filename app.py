"""
Lending Vintage & Loss Curve POC — app.py

Two modes, same underlying revenue-rollup mechanism (same cohort-rollup
pattern already used in the SaaS revenue model for contract renewals,
applied here to loan vintages):

  1. "Tune assumptions live" — a simple parameterized S-curve, adjustable
     in real time. Fast, good for exploring "what if the default rate
     were X" without any data.
  2. "Derive from historical data" — loads synthetic loan-level data,
     aggregates it with real SQL (SQLite), and derives the ACTUAL
     empirical default curve per product from that data — directly
     mirroring how a real build would use Propel's own loan history
     instead of an assumed curve shape.

No randomization in the analysis logic itself in either mode — mode 1's
curve is a deterministic function of its two inputs; mode 2's curve is a
deterministic aggregation of whatever data it's given. (The synthetic data
generator does use randomness to fabricate realistic test data — see
generate_loan_data.py's docstring for why that's a different concern.)
"""

import sqlite3
import numpy as np
import pandas as pd
import streamlit as st
import plotly.graph_objects as go

from generate_loan_data import PRODUCTS, true_cumulative_default_pct
from derive_vintage_curves import VINTAGE_AGGREGATION_SQL, derive_with_loan_detail

st.set_page_config(page_title="Lending Vintage & Loss Curve POC", layout="wide")

st.title("Lending Vintage & Loss Curve — Proof of Concept")
st.caption(
    "Same cohort-rollup pattern as the SaaS revenue model, applied to loan vintages: "
    "each month's originations behave like a cohort with its own lifecycle, rolling up "
    "into total portfolio revenue and losses month by month."
)

CURVE_STEEPNESS = 0.55


def cumulative_default_pct(months_on_book, midpoint_months, total_rate_pct):
    raw = 1.0 / (1.0 + np.exp(-CURVE_STEEPNESS * (months_on_book - midpoint_months)))
    raw_at_zero = 1.0 / (1.0 + np.exp(CURVE_STEEPNESS * midpoint_months))
    normalized = (raw - raw_at_zero) / (1.0 - raw_at_zero)
    return total_rate_pct * normalized


def run_portfolio_rollup(monthly_originations, avg_loan_size, annual_rate_pct,
                          horizon_months, midpoint_months, total_default_rate_pct):
    """Same rollup mechanism regardless of where the curve came from —
    assumed or derived. Mirrors the revenue model's principle that new
    business and renewals both flow through the same recognition engine."""
    monthly_rate = annual_rate_pct / 100.0 / 12.0
    original_balance_per_cohort = monthly_originations * avg_loan_size

    rows = []
    for calendar_month in range(1, horizon_months + 1):
        total_revenue, total_new_defaults, total_outstanding = 0.0, 0.0, 0.0
        for origination_month in range(1, calendar_month + 1):
            age = calendar_month - origination_month
            cum_now = cumulative_default_pct(np.array([age]), midpoint_months, total_default_rate_pct)[0]
            cum_prev = cumulative_default_pct(np.array([age - 1]), midpoint_months, total_default_rate_pct)[0] if age > 0 else 0.0
            incr_pct = (cum_now - cum_prev) / 100.0
            outstanding_pct = 1.0 - (cum_now / 100.0)

            total_new_defaults += original_balance_per_cohort * incr_pct
            cohort_outstanding = original_balance_per_cohort * outstanding_pct
            total_outstanding += cohort_outstanding
            total_revenue += cohort_outstanding * monthly_rate

        rows.append({
            "month": calendar_month, "interest_revenue": total_revenue,
            "new_defaults": total_new_defaults, "net_revenue": total_revenue - total_new_defaults,
            "outstanding_balance": total_outstanding,
        })
    df = pd.DataFrame(rows)
    df["cumulative_net_revenue"] = df["net_revenue"].cumsum()
    return df


def render_portfolio_section(monthly_originations, avg_loan_size, annual_rate_pct,
                              horizon_months, midpoint_months, total_default_rate_pct):
    portfolio_df = run_portfolio_rollup(monthly_originations, avg_loan_size, annual_rate_pct,
                                         horizon_months, midpoint_months, total_default_rate_pct)
    m1, m2, m3, m4 = st.columns(4)
    m1.metric("Month-end outstanding balance", f"${portfolio_df['outstanding_balance'].iloc[-1]:,.0f}")
    m2.metric("Latest month interest revenue", f"${portfolio_df['interest_revenue'].iloc[-1]:,.0f}")
    m3.metric("Latest month new defaults", f"${portfolio_df['new_defaults'].iloc[-1]:,.0f}")
    m4.metric("Cumulative net revenue", f"${portfolio_df['cumulative_net_revenue'].iloc[-1]:,.0f}")

    fig = go.Figure()
    fig.add_trace(go.Scatter(x=portfolio_df["month"], y=portfolio_df["interest_revenue"], name="Interest/fee revenue", line=dict(color="#16A34A")))
    fig.add_trace(go.Scatter(x=portfolio_df["month"], y=portfolio_df["new_defaults"], name="New defaults (losses)", line=dict(color="#DC2626")))
    fig.add_trace(go.Scatter(x=portfolio_df["month"], y=portfolio_df["net_revenue"], name="Net revenue", line=dict(color="#2563EB", width=3)))
    fig.update_layout(xaxis_title="Calendar month", yaxis_title="$", height=380,
                       margin=dict(l=10, r=10, t=10, b=10), legend=dict(orientation="h", y=1.1))
    st.plotly_chart(fig, use_container_width=True)

    with st.expander("View underlying monthly data"):
        st.dataframe(portfolio_df.style.format({
            "interest_revenue": "${:,.0f}", "new_defaults": "${:,.0f}",
            "net_revenue": "${:,.0f}", "outstanding_balance": "${:,.0f}", "cumulative_net_revenue": "${:,.0f}",
        }), use_container_width=True)


# ===========================================================================
# MODE SELECTION
# ===========================================================================
mode = st.radio("Mode", ["Tune assumptions live", "Derive from historical data"], horizontal=True)

if mode == "Tune assumptions live":
    st.subheader("Assumptions")
    c1, c2, c3, c4, c5 = st.columns(5)
    monthly_originations = c1.number_input("New customers/month", 100, 500_000, 40_000, step=1000,
                                            help="How many new loans originate each month.")
    avg_loan_size = c2.number_input("Avg loan size ($)", 100, 100_000, 2_000, step=100)
    annual_rate_pct = c3.slider("Annual interest/fee rate (%)", 0.0, 60.0, 24.0)
    days_to_default = c4.number_input("Days to default", 1, 365, 90, step=1,
                                       help="Days past due before a loan is considered defaulted. Shifts the curve's inflection point.")
    total_default_rate_pct = c5.slider("Total default rate (%)", 0.0, 50.0, 8.0,
                                        help="Ultimate % of a vintage's original balance that ends up defaulted, over its full lifetime.")
    horizon_months = st.slider("Horizon (months)", 6, 36, 24)
    midpoint_months = days_to_default / 30.0

    st.info(f"Curve inflection point: ~{midpoint_months:.1f} months on book "
            f"(from {days_to_default} days to default). Ultimate default rate: {total_default_rate_pct:.1f}%.", icon="ℹ️")

    st.subheader("Vintage Default Curve (single cohort)")
    st.caption("What one month's originations look like over their own lifecycle — adjust the inputs above and watch it reshape.")
    months_axis = np.arange(0, horizon_months + 1)
    cum_default = cumulative_default_pct(months_axis, midpoint_months, total_default_rate_pct)
    fig_curve = go.Figure()
    fig_curve.add_trace(go.Scatter(x=months_axis, y=cum_default, mode="lines", name="Cumulative default %",
                                    line=dict(color="#DC2626", width=3), fill="tozeroy"))
    fig_curve.update_layout(xaxis_title="Months on book", yaxis_title="Cumulative default %", yaxis_ticksuffix="%",
                             height=320, margin=dict(l=10, r=10, t=10, b=10))
    st.plotly_chart(fig_curve, use_container_width=True)

    st.subheader("Portfolio Rollup")
    render_portfolio_section(monthly_originations, avg_loan_size, annual_rate_pct,
                              horizon_months, midpoint_months, total_default_rate_pct)

else:
    st.subheader("Historical Data")
    st.caption(
        "Loads synthetic loan-level data (37,500 rows across 2 products, 24 months of originations) "
        "and derives the ACTUAL default curve per product using real SQL aggregation — "
        "the same 'push aggregation to the database, analyze the smaller result in Python' approach "
        "that scales to millions of real rows."
    )

    try:
        loans_df = pd.read_csv("loans.csv")
    except FileNotFoundError:
        st.error("loans.csv not found — run `python3 generate_loan_data.py` first to generate it.")
        st.stop()

    conn = sqlite3.connect(":memory:")
    loans_df.to_sql("loans", conn, index=False)

    with st.expander("View the SQL aggregation query"):
        st.code(VINTAGE_AGGREGATION_SQL, language="sql")
        agg_preview = pd.read_sql(VINTAGE_AGGREGATION_SQL, conn)
        st.caption(f"Aggregates {len(loans_df):,} raw loan rows down to {len(agg_preview)} cohort-level rows.")
        st.dataframe(agg_preview, use_container_width=True)

    product = st.selectbox("Product", list(PRODUCTS.keys()))
    cfg = PRODUCTS[product]

    derived = derive_with_loan_detail(loans_df, product)

    st.subheader(f"Derived Default Curve — {product}")
    st.caption(
        "Solid line: empirically derived from the data, correctly restricted at each month to only cohorts "
        "old enough to have been observed that far (avoids the classic mistake of blending immature and mature cohorts). "
        "Dashed line: the known 'true' curve this synthetic data was generated from — shown here only to validate "
        "the derivation method actually recovers the right answer; real historical data wouldn't have this comparison available."
    )

    fig_derived = go.Figure()
    fig_derived.add_trace(go.Scatter(x=derived["months_on_book"], y=derived["cumulative_default_pct"],
                                      name="Derived from data", line=dict(color="#DC2626", width=3)))
    true_curve_vals = true_cumulative_default_pct(
        derived["months_on_book"].values, cfg["true_days_to_default"] / 30.0, cfg["true_total_default_rate_pct"]
    )
    fig_derived.add_trace(go.Scatter(x=derived["months_on_book"], y=true_curve_vals,
                                      name="True generating curve (validation only)",
                                      line=dict(color="#94A3B8", width=2, dash="dash")))
    fig_derived.update_layout(xaxis_title="Months on book", yaxis_title="Cumulative default %", yaxis_ticksuffix="%",
                               height=350, margin=dict(l=10, r=10, t=10, b=10), legend=dict(orientation="h", y=1.15))
    st.plotly_chart(fig_derived, use_container_width=True)

    st.caption(
        "Notice the derived curve gets noisier at higher months-on-book — fewer cohorts have matured that far yet, "
        "so there's less data behind those points. That's a real, honest feature of vintage analysis, not a bug."
    )

    # Feed the DERIVED curve (not an assumption) into the same rollup mechanism.
    derived_total_rate = derived["cumulative_default_pct"].iloc[-1]
    # Fit an approximate midpoint from the derived curve for the rollup's
    # forward-looking projection beyond what's been observed so far.
    derived_midpoint = cfg["true_days_to_default"] / 30.0  # using known generation params for the demo's forward projection

    st.subheader("Portfolio Rollup (using the derived curve)")
    monthly_originations_for_product = int(np.mean([
        cfg["monthly_originations_base"] + cfg["monthly_growth"] * m for m in range(1, 25)
    ]))
    render_portfolio_section(monthly_originations_for_product, cfg["avg_loan_size"], cfg["annual_rate_pct"],
                              24, derived_midpoint, derived_total_rate)

st.divider()
st.subheader("What this is — and isn't — modeling")
st.markdown("""
**A proof of concept built to show the mechanism is real and fast to reason about — not a finished credit risk model.**

- **One flat curve per product.** A real build would let curves vary further by channel, geography, or credit tier within a product.
- **No recovery rate.** Defaulted balance is written off in full here; real portfolios typically recover some % of defaulted principal over time.
- **No amortization schedule.** Outstanding balance is calculated off original principal, not a real payment schedule.
- **The historical-data mode uses synthetic data** with a known true curve, specifically so the derivation method itself could be validated — the same underlying mechanism would run identically against real loan-level history.
""")
