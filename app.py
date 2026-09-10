"""
CLAB Forecast POC — app.py

A lending-funnel forecasting proof of concept: applications -> approvals ->
originations -> CLAB roll-forward (repayments + charge-offs) -> revenue,
with default rates driven by a vintage curve that can be either assumed
(tunable inputs) or fitted to historical loan-level data via real SQL
aggregation.

Same visual language as the SaaS revenue model (navy/green/blue/purple/
amber/red palette, card styling, typography) — not a pixel-identical
rebuild, kept simple and fast to navigate.
"""

import pandas as pd
import streamlit as st
import plotly.graph_objects as go

from generate_loan_data import PRODUCTS as HIST_PRODUCTS, true_cumulative_default_pct
from derive_vintage_curves import (LOANS_CSV, VINTAGE_TRIANGLE_SQL, load_into_sqlite,
                                   build_vintage_triangle, pooled_default_curve, fit_default_curve)
from clab_forecast_engine import forecast_clab, aggregate_to_quarterly, cumulative_default_pct

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
    "(Ending = Beginning + New − Runoff − Losses), applied to a loan book instead of a subscription book."
)


def _fmt_dollar_scaled(val):
    """Same auto-scaling convention as the SaaS revenue model."""
    if val is None or pd.isna(val):
        return "—"
    sign = "−" if val < 0 else ""
    val = abs(val)
    if val >= 1_000_000:
        return f"{sign}${val / 1_000_000:,.2f}M"
    if val >= 1_000:
        return f"{sign}${val / 1_000:,.2f}K"
    return f"{sign}${val:,.0f}"


DOLLAR_COLS = ["originations", "beginning_clab", "principal_repaid", "charge_offs", "ending_clab", "revenue"]


def _display_table(df):
    out = df.copy()
    for col in DOLLAR_COLS:
        out[col] = out[col].apply(_fmt_dollar_scaled)
    out["applications"] = out["applications"].round(0)
    return out


@st.cache_data
def load_vintage_data():
    """Loads the loan-level history once, builds the vintage triangle in SQL,
    and fits one default curve per product. Cached — reruns from moving a
    slider don't repeat any of it."""
    loans_df = pd.read_csv(LOANS_CSV)
    conn = load_into_sqlite(loans_df)
    triangle = build_vintage_triangle(conn)
    conn.close()
    fits = {p: fit_default_curve(pooled_default_curve(triangle, p)) for p in HIST_PRODUCTS}
    return len(loans_df), triangle, fits


PRODUCT_DEFAULTS = {
    "Short-Term": dict(applications=30000, approval_rate=30.0, avg_loan_size=1500.0, annual_yield=100.0,
                        term_months=12, days_to_default=60, total_default_rate=12.0, color=RED),
    "Installment": dict(applications=12000, approval_rate=45.0, avg_loan_size=4000.0, annual_yield=55.0,
                         term_months=24, days_to_default=150, total_default_rate=6.0, color=BLUE),
}

# ===========================================================================
# ASSUMPTIONS
# ===========================================================================
st.subheader("Forecast Settings")
s1, s2 = st.columns(2)
horizon_months = s1.slider("Horizon (months)", 6, 36, 24)
use_derived_curve = s2.checkbox("Overlay default curve fitted to historical data (vintage analysis)", value=False,
                                 help="Off: use the assumption inputs below directly. On: fit the default curve to mock historical loan-level data (SQL vintage triangle), and use that instead.")

product_tabs = st.tabs(list(PRODUCT_DEFAULTS.keys()) + ["Combined"])
product_forecasts = {}

# Load historical data once if needed
if use_derived_curve:
    try:
        _, _, fitted_curves = load_vintage_data()
    except FileNotFoundError:
        st.error("loans.csv not found — run `python generate_loan_data.py` first.")
        st.stop()

for i, product in enumerate(PRODUCT_DEFAULTS.keys()):
    with product_tabs[i]:
        defaults = PRODUCT_DEFAULTS[product]
        product_color = defaults["color"]
        st.markdown(f"<h3 style='color:{product_color};'>{product}</h3>", unsafe_allow_html=True)

        c1, c2, c3, c4, c5 = st.columns(5)
        applications = c1.number_input("Applications/month", 100, 500_000, defaults["applications"], step=500,
                                        key=f"{product}_apps", help="Baseline monthly application volume, before seasonality.")
        approval_rate = c2.slider("Approval rate (%)", 1.0, 100.0, defaults["approval_rate"], key=f"{product}_appr")
        avg_loan_size = c3.number_input("Avg loan size ($)", 100, 100_000, int(defaults["avg_loan_size"]), step=100, key=f"{product}_size")
        annual_yield = c4.slider("Annual yield (%)", 0.0, 200.0, defaults["annual_yield"], key=f"{product}_yield",
                                  help="Annualized yield on the loan book. Also the contractual rate behind the repayment "
                                       "schedule — the interest borrowers pay is the revenue.")
        term_months = c5.number_input("Loan term (months)", 1, 60, defaults["term_months"], key=f"{product}_term",
                                       help="Loans repay on a level-payment schedule over this term, shrinking CLAB as they do.")

        with st.expander("Seasonality (12-month pattern)"):
            st.caption("Explicit, user-set monthly multipliers — cycles automatically for horizons beyond 12 months.")
            month_labels = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"]
            season_cols = st.columns(6)
            seasonality = [
                season_cols[m % 6].slider(month_labels[m], 0.5, 1.5, 1.0, key=f"{product}_season_{m}")
                for m in range(12)
            ]

        if use_derived_curve:
            fit = fitted_curves[product]
            total_default_rate = fit["total_default_rate_pct"]
            midpoint_months = fit["midpoint_months"]
            st.info(f"Using default curve fitted to historical data: {total_default_rate:.2f}% total default rate, "
                    f"~{fit['days_to_default']:.0f} days to default (see 'Vintage Analysis' below).", icon="📊")
        else:
            d1, d2 = st.columns(2)
            days_to_default = d1.number_input("Days to default", 1, 365, defaults["days_to_default"], key=f"{product}_dtd")
            total_default_rate = d2.slider("Total default rate (%)", 0.0, 50.0, defaults["total_default_rate"], key=f"{product}_tdr")
            midpoint_months = days_to_default / 30.0

        share_of_curve_within_term = cumulative_default_pct(term_months, midpoint_months, 1.0)
        if share_of_curve_within_term < 0.95:
            st.warning(f"Only {share_of_curve_within_term:.0%} of the default curve falls within the {term_months}-month term. "
                       f"Loans that have already repaid can't default, so realized losses will run below the "
                       f"{total_default_rate:.1f}% headline rate.")

        forecast_df = forecast_clab(
            monthly_applications_base=applications, seasonality_pattern=seasonality,
            approval_rate_pct=approval_rate, avg_loan_size=avg_loan_size, annual_yield_pct=annual_yield,
            midpoint_months=midpoint_months, total_default_rate_pct=total_default_rate,
            term_months=term_months, horizon_months=horizon_months,
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
        st.plotly_chart(fig, width="stretch")

        with st.expander("View underlying monthly data"):
            st.dataframe(_display_table(forecast_df), width="stretch")

# ===========================================================================
# COMBINED VIEW
# ===========================================================================
with product_tabs[-1]:
    st.markdown(f"<h3 style='color:{NAVY};'>Combined — All Products</h3>", unsafe_allow_html=True)
    combined_df = product_forecasts[list(PRODUCT_DEFAULTS.keys())[0]][["month"]].copy()
    for col in ["applications"] + DOLLAR_COLS:
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
    st.plotly_chart(fig_combined, width="stretch")

    st.markdown("#### CLAB Bridge (full horizon)")
    beginning = combined_df["beginning_clab"].iloc[0]
    originated = combined_df["originations"].sum()
    repaid = combined_df["principal_repaid"].sum()
    charged_off = combined_df["charge_offs"].sum()
    ending = combined_df["ending_clab"].iloc[-1]
    # Floating bars (base + height) rather than go.Waterfall, so repayments (healthy runoff)
    # and charge-offs (losses) can be colored differently — Waterfall only allows one "decrease" color.
    fig_bridge = go.Figure(go.Bar(
        x=["Beginning CLAB", "Originations", "Principal repaid", "Charge-offs", "Ending CLAB"],
        base=[0, beginning, beginning + originated - repaid, ending, 0],
        y=[beginning, originated, repaid, charged_off, ending],
        marker_color=[NAVY, GREEN, AMBER, RED, NAVY],
        text=[_fmt_dollar_scaled(v) for v in [beginning, originated, -repaid, -charged_off, ending]],
        textposition="outside", hoverinfo="skip",
    ))
    fig_bridge.update_layout(yaxis_title="$", height=360, margin=dict(l=10, r=10, t=30, b=10), showlegend=False)
    st.plotly_chart(fig_bridge, width="stretch")

    st.markdown("#### Quarterly Rollup (matches how CLAB is reported externally)")
    quarterly_df = aggregate_to_quarterly(combined_df)
    st.dataframe(_display_table(quarterly_df)[["quarter", "applications", "originations", "beginning_clab",
                                                "principal_repaid", "charge_offs", "ending_clab", "revenue"]],
                 width="stretch")
    trailing_months = horizon_months % 3
    if trailing_months:
        first_trailing = horizon_months - trailing_months + 1
        if trailing_months == 1:
            partial_note = f"Month {horizon_months} falls in a partial quarter and is left out of this table — it's"
        else:
            partial_note = f"Months {first_trailing}–{horizon_months} fall in a partial quarter and are left out of this table — they're"
        st.caption(f"{partial_note} still in the monthly data and the bridge above.")

# ===========================================================================
# VINTAGE ANALYSIS — the "how am I doing it, how am I overlaying it" section
# ===========================================================================
st.divider()
st.markdown(f"<h2 style='color:{NAVY};'>Vintage Analysis — Historical Data</h2>", unsafe_allow_html=True)

try:
    loan_row_count, triangle, fitted_curves_display = load_vintage_data()
except FileNotFoundError:
    loan_row_count = None
    st.error("loans.csv not found — run `python generate_loan_data.py` first.")

if loan_row_count is not None:
    st.caption(
        f"Mock historical loan-level data ({loan_row_count:,} rows across 2 products, 24 months of originations). "
        "SQL builds the vintage triangle — the same approach that scales to millions of real rows: push "
        "aggregation to the database, analyze the smaller result in Python."
    )

    with st.expander("View the SQL vintage triangle query"):
        st.code(VINTAGE_TRIANGLE_SQL, language="sql")
        st.caption(f"Aggregates {loan_row_count:,} raw loan rows down to {len(triangle)} cohort × months-on-book rows. "
                   "The JOIN only gives each cohort rows for ages it has actually been observed at — that's how "
                   "censoring is handled: a 4-month-old cohort says nothing about month 8.")

    vintage_product = st.selectbox("Product", list(HIST_PRODUCTS.keys()), key="vintage_product_select")
    cfg = HIST_PRODUCTS[vintage_product]
    fit = fitted_curves_display[vintage_product]
    pooled = pooled_default_curve(triangle, vintage_product)

    v1, v2, v3, v4 = st.columns(4)
    v1.metric("Fitted total default rate", f"{fit['total_default_rate_pct']:.2f}%")
    v2.metric("True rate (validation only)", f"{cfg['true_total_default_rate_pct']:.2f}%")
    v3.metric("Fitted days to default", f"{fit['days_to_default']:.0f}")
    v4.metric("True days (validation only)", f"{cfg['true_days_to_default']}")

    ages = pooled["months_on_book"].to_numpy(dtype=float)
    fig_vintage = go.Figure()
    fig_vintage.add_trace(go.Scatter(x=ages, y=pooled["cumulative_default_pct"], name="Pooled from data (SQL triangle)",
                                      mode="lines+markers", line=dict(color=RED, width=2),
                                      customdata=pooled["cohorts"],
                                      hovertemplate="Month %{x}: %{y:.2f}%<br>%{customdata} cohort(s) observed<extra></extra>"))
    fig_vintage.add_trace(go.Scatter(x=ages, y=cumulative_default_pct(ages, fit["midpoint_months"], fit["total_default_rate_pct"]),
                                      name="Fitted curve (feeds the forecast)", line=dict(color=NAVY, width=3)))
    true_vals = true_cumulative_default_pct(ages, cfg["true_days_to_default"] / 30.0, cfg["true_total_default_rate_pct"])
    fig_vintage.add_trace(go.Scatter(x=ages, y=true_vals, name="True generating curve (validation only)",
                                      line=dict(color="#94A3B8", width=2, dash="dash")))
    fig_vintage.update_layout(xaxis_title="Months on book", yaxis_title="Cumulative default %", yaxis_ticksuffix="%",
                               height=350, margin=dict(l=10, r=10, t=10, b=10), legend=dict(orientation="h", y=1.15))
    st.plotly_chart(fig_vintage, width="stretch")
    st.caption(
        "The pooled curve gets noisier at higher months-on-book — fewer cohorts have matured that far yet (month 23 is "
        "a single cohort). The fit is weighted by the balance behind each point, so those thin late points can't drag "
        "it around. Toggle 'Overlay default curve fitted to historical data' above to feed the fitted curve into the "
        "forecast directly."
    )

    st.markdown("#### Vintage triangle — cumulative default % by cohort")
    product_triangle = triangle[triangle["product"] == vintage_product]
    heatmap = product_triangle.pivot(index="origination_month", columns="months_on_book", values="cum_default_pct")
    fig_triangle = go.Figure(go.Heatmap(
        z=heatmap.values, x=heatmap.columns, y=heatmap.index, colorscale="Reds",
        colorbar=dict(title="Cum. default %", ticksuffix="%"),
        hovertemplate="Cohort month %{y}, month on book %{x}: %{z:.2f}%<extra></extra>",
    ))
    fig_triangle.update_layout(xaxis_title="Months on book", yaxis_title="Origination month (cohort)",
                                yaxis_autorange="reversed", height=420, margin=dict(l=10, r=10, t=10, b=10))
    st.plotly_chart(fig_triangle, width="stretch")
    st.caption("Each row is one month's originations aging left to right; the blank lower-right is ages newer cohorts "
               "haven't reached yet. Reading down a column compares cohorts at the same age — the standard way "
               "to spot whether recent vintages are performing better or worse than older ones.")

st.divider()
st.markdown("#### What this is — and isn't — modeling")
st.markdown("""
- **Repayment follows a level-payment schedule over each product's term, with no prepayment.** Real borrowers often pay off early, which shortens loan life further — not modeled.
- **Charge-offs are taken at the balance the defaulting loan still owed, with no recoveries** — so charge-offs here are gross, not net of collections.
- **The forecast starts from an empty book.** The historical loans are used to fit the default curve, not carried in as opening CLAB.
- **Originations = Applications × Approval Rate × Avg Loan Size directly** — no separate "approved but didn't take the loan" step modeled.
- **Annual yield is both the revenue yield and the contractual rate behind the repayment schedule** — fees aren't modeled separately.
- **Only the default curve's total rate and timing are fitted; its steepness is a fixed shape assumption**, shared by the assumption-based and fitted modes.
- **The historical data is synthetic**, with a known true curve baked in specifically so the derivation method could be validated against a ground truth — the same mechanism would run identically against real loan-level history.
""")
