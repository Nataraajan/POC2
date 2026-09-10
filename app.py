"""
CLAB Forecast POC — app.py

A lending-funnel forecasting proof of concept: applications -> approvals ->
originations -> CLAB roll-forward -> revenue, with default rates driven by
a vintage curve that can be either assumed (tunable sliders) or derived
from historical loan-level data via real SQL aggregation.

Same visual language as the SaaS revenue model (navy/green/blue/purple/
amber/red palette, card styling, typography) — not a pixel-identical
rebuild, kept simple and fast to navigate.
"""

import sqlite3
import numpy as np
import pandas as pd
import streamlit as st
import plotly.graph_objects as go

from generate_loan_data import PRODUCTS as HIST_PRODUCTS, true_cumulative_default_pct
from derive_vintage_curves import VINTAGE_AGGREGATION_SQL, derive_with_loan_detail
from clab_forecast_engine import forecast_clab, aggregate_to_quarterly

NAVY = "#1E2761"
GREEN = "#16A34A"
BLUE = "#2563EB"
PURPLE = "#9333EA"
AMBER = "#D97706"
RED = "#DC2626"

st.set_page_config(page_title="CLAB Forecast POC", layout="wide")

st.markdown(f"""
<style>
    div[data-testid="stNumberInput"] input {{ max-width: 130px; }}
    .card-title {{ color: {NAVY}; font-weight: 700; }}
    div.stButton > button:first-child {{ background-color: {NAVY}; color: white; }}
</style>
""", unsafe_allow_html=True)

st.markdown(f"<h1 style='color:{NAVY};'>CLAB Forecast — Applications to Portfolio Revenue</h1>", unsafe_allow_html=True)
st.caption(
    "Applications → approvals → originations → CLAB roll-forward → revenue. "
    "Same balance-roll-forward pattern as the SaaS revenue model's ARR bridge "
    "(Ending = Beginning + New − Losses), applied to a loan book instead of a subscription book."
)


def _fmt_dollar_scaled(val):
    """Same auto-scaling convention as the SaaS revenue model."""
    if val is None or pd.isna(val):
        return "—"
    if abs(val) >= 1_000_000:
        return f"${val / 1_000_000:,.2f}M"
    if abs(val) >= 1_000:
        return f"${val / 1_000:,.2f}K"
    return f"${val:,.0f}"


PRODUCT_DEFAULTS = {
    "Short-Term": dict(applications=30000, approval_rate=30.0, avg_loan_size=1500.0,
                        annual_yield=100.0, days_to_default=60, total_default_rate=12.0, color=RED),
    "Installment": dict(applications=12000, approval_rate=45.0, avg_loan_size=4000.0,
                         annual_yield=55.0, days_to_default=150, total_default_rate=6.0, color=BLUE),
}

# ===========================================================================
# ASSUMPTIONS
# ===========================================================================
st.subheader("Forecast Settings")
s1, s2 = st.columns(2)
horizon_months = s1.slider("Horizon (months)", 6, 36, 24)
use_derived_curve = s2.checkbox("Overlay default curve derived from historical data (vintage analysis)", value=False,
                                 help="Off: use the assumption sliders below directly. On: derive the default curve from mock historical loan-level data via SQL aggregation, and use that instead.")

product_tabs = st.tabs(list(PRODUCT_DEFAULTS.keys()) + ["Combined"])
product_forecasts = {}
product_configs = {}

# Load historical data once if needed
loans_df = None
if use_derived_curve:
    try:
        loans_df = pd.read_csv("loans.csv")
    except FileNotFoundError:
        st.error("loans.csv not found — run `python3 generate_loan_data.py` first.")
        st.stop()

for i, product in enumerate(PRODUCT_DEFAULTS.keys()):
    with product_tabs[i]:
        defaults = PRODUCT_DEFAULTS[product]
        product_color = defaults["color"]
        st.markdown(f"<h3 style='color:{product_color};'>{product}</h3>", unsafe_allow_html=True)

        c1, c2, c3, c4 = st.columns(4)
        applications = c1.number_input("Applications/month", 100, 500_000, defaults["applications"], step=500,
                                        key=f"{product}_apps", help="Baseline monthly application volume, before seasonality.")
        approval_rate = c2.slider("Approval rate (%)", 1.0, 100.0, defaults["approval_rate"], key=f"{product}_appr")
        avg_loan_size = c3.number_input("Avg loan size ($)", 100, 100_000, int(defaults["avg_loan_size"]), step=100, key=f"{product}_size")
        annual_yield = c4.slider("Annual yield (%)", 0.0, 200.0, defaults["annual_yield"], key=f"{product}_yield",
                                  help="Annualized revenue yield applied to ending CLAB each month.")

        with st.expander("Seasonality (12-month pattern)"):
            st.caption("Explicit, user-set monthly multipliers — cycles automatically for horizons beyond 12 months.")
            month_labels = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"]
            season_cols = st.columns(6)
            seasonality = [
                season_cols[m % 6].slider(month_labels[m], 0.5, 1.5, 1.0, key=f"{product}_season_{m}")
                for m in range(12)
            ]

        if use_derived_curve:
            derived = derive_with_loan_detail(loans_df, product)
            total_default_rate = derived["cumulative_default_pct"].iloc[-1]
            midpoint_months = HIST_PRODUCTS[product]["true_days_to_default"] / 30.0
            st.info(f"Using derived curve: {total_default_rate:.2f}% total default rate "
                    f"(from historical vintage analysis — see 'Vintage Analysis' tab below).", icon="📊")
        else:
            d1, d2 = st.columns(2)
            days_to_default = d1.number_input("Days to default", 1, 365, defaults["days_to_default"], key=f"{product}_dtd")
            total_default_rate = d2.slider("Total default rate (%)", 0.0, 50.0, defaults["total_default_rate"], key=f"{product}_tdr")
            midpoint_months = days_to_default / 30.0

        product_configs[product] = dict(applications=applications, approval_rate=approval_rate,
                                         avg_loan_size=avg_loan_size, annual_yield=annual_yield,
                                         midpoint_months=midpoint_months, total_default_rate=total_default_rate)

        forecast_df = forecast_clab(
            monthly_applications_base=applications, seasonality_pattern=seasonality,
            approval_rate_pct=approval_rate, avg_loan_size=avg_loan_size, annual_yield_pct=annual_yield,
            midpoint_months=midpoint_months, total_default_rate_pct=total_default_rate,
            horizon_months=horizon_months,
        )
        product_forecasts[product] = forecast_df

        m1, m2, m3, m4 = st.columns(4)
        m1.metric("Ending CLAB", _fmt_dollar_scaled(forecast_df["ending_clab"].iloc[-1]))
        m2.metric("Latest month revenue", _fmt_dollar_scaled(forecast_df["revenue"].iloc[-1]))
        m3.metric("Latest month charge-offs", _fmt_dollar_scaled(forecast_df["charge_offs"].iloc[-1]))
        m4.metric("Total revenue (horizon)", _fmt_dollar_scaled(forecast_df["revenue"].sum()))

        fig = go.Figure()
        fig.add_trace(go.Scatter(x=forecast_df["month"], y=forecast_df["ending_clab"], name="Ending CLAB",
                                  line=dict(color=defaults["color"], width=3), fill="tozeroy"))
        fig.update_layout(xaxis_title="Month", yaxis_title="$", height=320, margin=dict(l=10, r=10, t=10, b=10))
        st.plotly_chart(fig, use_container_width=True)

        with st.expander("View underlying monthly data"):
            display_df = forecast_df.copy()
            for col in ["applications", "originations", "beginning_clab", "charge_offs", "ending_clab", "revenue"]:
                if col != "applications":
                    display_df[col] = display_df[col].apply(_fmt_dollar_scaled)
                else:
                    display_df[col] = display_df[col].round(0)
            st.dataframe(display_df, use_container_width=True)

# ===========================================================================
# COMBINED VIEW
# ===========================================================================
with product_tabs[-1]:
    st.markdown(f"<h3 style='color:{NAVY};'>Combined — All Products</h3>", unsafe_allow_html=True)
    combined_df = product_forecasts[list(PRODUCT_DEFAULTS.keys())[0]][["month"]].copy()
    for col in ["applications", "originations", "beginning_clab", "charge_offs", "ending_clab", "revenue"]:
        combined_df[col] = sum(product_forecasts[p][col] for p in PRODUCT_DEFAULTS.keys())

    m1, m2, m3, m4 = st.columns(4)
    m1.metric("Ending CLAB", _fmt_dollar_scaled(combined_df["ending_clab"].iloc[-1]))
    m2.metric("Latest month revenue", _fmt_dollar_scaled(combined_df["revenue"].iloc[-1]))
    m3.metric("Latest month charge-offs", _fmt_dollar_scaled(combined_df["charge_offs"].iloc[-1]))
    m4.metric("Total revenue (horizon)", _fmt_dollar_scaled(combined_df["revenue"].sum()))

    fig_combined = go.Figure()
    fig_combined.add_trace(go.Scatter(x=combined_df["month"], y=combined_df["revenue"], name="Revenue", line=dict(color=GREEN, width=3)))
    fig_combined.add_trace(go.Scatter(x=combined_df["month"], y=combined_df["charge_offs"], name="Charge-offs", line=dict(color=RED, width=2)))
    fig_combined.add_trace(go.Scatter(x=combined_df["month"], y=combined_df["ending_clab"], name="Ending CLAB", line=dict(color=NAVY, width=3, dash="dot")))
    fig_combined.update_layout(xaxis_title="Month", yaxis_title="$", height=380, margin=dict(l=10, r=10, t=10, b=10),
                                legend=dict(orientation="h", y=1.1))
    st.plotly_chart(fig_combined, use_container_width=True)

    st.markdown("#### Quarterly Rollup (matches how CLAB is reported externally)")
    quarterly_df = aggregate_to_quarterly(combined_df)
    display_q = quarterly_df.copy()
    for col in ["applications", "originations", "charge_offs", "revenue", "ending_clab", "beginning_clab"]:
        if col != "applications":
            display_q[col] = display_q[col].apply(_fmt_dollar_scaled)
        else:
            display_q[col] = display_q[col].round(0)
    st.dataframe(display_q, use_container_width=True)

# ===========================================================================
# VINTAGE ANALYSIS — the "how am I doing it, how am I overlaying it" section
# ===========================================================================
st.divider()
st.markdown(f"<h2 style='color:{NAVY};'>Vintage Analysis — Historical Data</h2>", unsafe_allow_html=True)
st.caption(
    "Mock historical loan-level data (37,500 rows across 2 products, 24 months of originations), "
    "aggregated with real SQL — the same approach that scales to millions of real rows: push "
    "aggregation to the database, analyze the smaller result in Python."
)

try:
    loans_df_display = pd.read_csv("loans.csv")
    conn = sqlite3.connect(":memory:")
    loans_df_display.to_sql("loans", conn, index=False)

    with st.expander("View the SQL aggregation query"):
        st.code(VINTAGE_AGGREGATION_SQL, language="sql")
        agg_preview = pd.read_sql(VINTAGE_AGGREGATION_SQL, conn)
        st.caption(f"Aggregates {len(loans_df_display):,} raw loan rows down to {len(agg_preview)} cohort-level rows.")

    vintage_product = st.selectbox("Product", list(HIST_PRODUCTS.keys()), key="vintage_product_select")
    cfg = HIST_PRODUCTS[vintage_product]
    derived_curve = derive_with_loan_detail(loans_df_display, vintage_product)

    fig_vintage = go.Figure()
    fig_vintage.add_trace(go.Scatter(x=derived_curve["months_on_book"], y=derived_curve["cumulative_default_pct"],
                                      name="Derived from data", line=dict(color=RED, width=3)))
    true_vals = true_cumulative_default_pct(derived_curve["months_on_book"].values,
                                             cfg["true_days_to_default"] / 30.0, cfg["true_total_default_rate_pct"])
    fig_vintage.add_trace(go.Scatter(x=derived_curve["months_on_book"], y=true_vals,
                                      name="True generating curve (validation only)",
                                      line=dict(color="#94A3B8", width=2, dash="dash")))
    fig_vintage.update_layout(xaxis_title="Months on book", yaxis_title="Cumulative default %", yaxis_ticksuffix="%",
                               height=350, margin=dict(l=10, r=10, t=10, b=10), legend=dict(orientation="h", y=1.15))
    st.plotly_chart(fig_vintage, use_container_width=True)
    st.caption(
        "The derived curve gets noisier at higher months-on-book — fewer cohorts have matured that far yet. "
        "That's a real, honest feature of vintage analysis with immature data, not a bug. Toggle "
        "'Overlay default curve derived from historical data' above to feed this into the forecast directly."
    )
except FileNotFoundError:
    st.error("loans.csv not found — run `python3 generate_loan_data.py` first.")

st.divider()
st.markdown("#### What this is — and isn't — modeling")
st.markdown("""
- **CLAB shrinks only from defaults here, not a separate paydown/amortization mechanic.** Real CLAB also shrinks from normal loan repayment — flagged, not modeled, to keep this POC focused on the funnel-to-balance mechanism and the vintage-curve overlay specifically.
- **Originations = Applications × Approval Rate × Avg Loan Size directly** — no separate "approved but didn't take the loan" step modeled.
- **The historical data is synthetic**, with a known true curve baked in specifically so the derivation method could be validated against a ground truth — the same mechanism would run identically against real loan-level history.
- **Revenue = Ending CLAB × monthly yield** — a simplification of average daily balance methodology real yield calculations often use.
""")
