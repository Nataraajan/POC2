"""Driver dashboard backed by the unchanged cohort forecast engine."""

import json
import numpy as np
import plotly.graph_objects as go
import streamlit as st
from clab_forecast_engine_v2 import (
    forecast_clab_v2,
    cumulative_default_pct,
    aggregate_to_quarterly,
)
from derive_vintage_curves import pooled_default_curve
from dashboard_support import (
    PRODUCT_DEFAULTS,
    DOLLAR_COLS,
    load_vintage_data,
    _fmt_dollar_scaled,
    gross_reserve_net_display,
)

st.set_page_config(page_title="CLAB | Driver forecast", layout="wide")
st.markdown(
    """<style>
.stApp {background:#f5f7fb;} .block-container {padding-top:2rem;max-width:1600px;}
h1,h2,h3 {color:#1e2761;letter-spacing:-.025em;}
[data-testid="stSidebar"] {background:white;border-right:1px solid #e2e8f0;}
[data-testid="stMetric"] {background:white;border:1px solid #e2e8f0;border-radius:12px;padding:16px;}
[data-testid="stMetricValue"] {color:#1e2761;font-size:1.8rem;}
</style>""",
    unsafe_allow_html=True,
)


def reset_drivers():
    for key in list(st.session_state):
        if key.startswith("driver_"):
            del st.session_state[key]


def switch_source():
    st.session_state.driver_source = (
        "Manual assumptions"
        if st.session_state.driver_source == "Historical vintage"
        else "Historical vintage"
    )


def inputs(product, historical):
    d = PRODUCT_DEFAULTS[product]
    prefix = f"driver_{product}_"
    fields = {
        "apps": d["applications"],
        "approval": d["approval_rate"],
        "size": int(d["avg_loan_size"]),
        "yield": d["annual_yield"],
        "term": d["term_months"],
        "days": d["days_to_default"],
        "rate": d["total_default_rate"],
    }
    for field, default in fields.items():
        st.session_state.setdefault(prefix + field, default)
    st.caption("DEMAND & UNDERWRITING")
    st.number_input("Applications / month", 0, 500000, step=500, key=prefix + "apps")
    st.slider("Approval rate (%)", 0.0, 100.0, key=prefix + "approval")
    st.number_input("Average loan size ($)", 100, 100000, step=100, key=prefix + "size")
    st.caption("PORTFOLIO & REVENUE")
    st.number_input("Loan term (months)", 1, 60, key=prefix + "term")
    st.slider("Annual yield (%)", 0.0, 200.0, key=prefix + "yield")
    st.caption("MANUAL DEFAULT ASSUMPTIONS")
    st.slider(
        "Lifetime default rate (%)", 0.0, 50.0, key=prefix + "rate", disabled=historical
    )
    st.number_input("Days to default", 1, 365, key=prefix + "days", disabled=historical)
    with st.expander("Seasonality"):
        st.caption("Multipliers for forecast months 1–12, repeated annually.")
        for m in range(12):
            st.session_state.setdefault(prefix + f"season_{m}", 1.0)
            st.slider(f"Month {m+1}", 0.5, 1.5, key=prefix + f"season_{m}")


def assumptions(product, fits, historical, horizon):
    ss, p = st.session_state, f"driver_{product}_"
    fit = fits[product] if historical else None
    return dict(
        monthly_applications_base=ss[p + "apps"],
        seasonality_pattern=[ss[p + f"season_{m}"] for m in range(12)],
        approval_rate_pct=ss[p + "approval"],
        avg_loan_size=ss[p + "size"],
        annual_yield_pct=ss[p + "yield"],
        term_months=ss[p + "term"],
        horizon_months=horizon,
        midpoint_months=fit["midpoint_months"] if fit else ss[p + "days"] / 30,
        total_default_rate_pct=fit["total_default_rate_pct"] if fit else ss[p + "rate"],
    )


def layout(fig, title, ytitle):
    fig.update_layout(
        title=title,
        height=350,
        paper_bgcolor="white",
        plot_bgcolor="white",
        margin=dict(l=20, r=20, t=65, b=20),
        hovermode="x unified",
        legend=dict(orientation="h", y=-0.22),
        yaxis_title=ytitle,
        font=dict(color="#334155"),
    )
    fig.update_yaxes(gridcolor="#edf0f5")
    return fig


def table(frame):
    labels = {
        "month": "Month",
        "quarter": "Quarter",
        "applications": "Applications",
        "originations": "Originations",
        "beginning_gross_clab": "Opening gross CLAB",
        "principal_repaid": "Principal repayments",
        "charge_offs": "Charge-offs",
        "ending_gross_clab": "Closing gross CLAB",
        "new_provisions": "Provision expense",
        "beginning_reserve": "Opening reserve",
        "ending_reserve": "Closing reserve",
        "net_clab": "Net CLAB",
        "revenue": "Revenue",
        "net_revenue": "Net revenue",
    }
    st.dataframe(
        frame.rename(columns=labels),
        hide_index=True,
        width="stretch",
        column_config={
            labels[c]: st.column_config.NumberColumn(format="dollar")
            for c in DOLLAR_COLS
            if c in frame
        },
    )


try:
    row_count, triangle, fits = load_vintage_data()
except (FileNotFoundError, ValueError) as exc:
    st.error(f"Historical data could not be loaded: {exc}")
    st.stop()

with st.sidebar:
    st.markdown("### Forecast drivers")
    st.caption("Adjust assumptions to update the entire forecast.")
    horizon = st.slider("Forecast horizon (months)", 6, 36, 24, key="driver_horizon")
    mode = st.radio(
        "Default curve source",
        ["Manual assumptions", "Historical vintage"],
        key="driver_source",
    )
    historical = mode == "Historical vintage"
    for product in PRODUCT_DEFAULTS:
        with st.expander(product, expanded=product == "Short-Term"):
            inputs(product, historical)
    st.button("Reset drivers", on_click=reset_drivers, width="stretch")

st.caption("CLAB / FINANCIAL PLANNING")
st.title("From drivers to revenue")
st.caption(
    "Applications → approvals → originations → loan book → revenue. Change a driver and see the monthly impact."
)
view = st.radio(
    "Portfolio", list(PRODUCT_DEFAULTS) + ["Combined"], horizontal=True, key="portfolio"
)
selected = list(PRODUCT_DEFAULTS) if view == "Combined" else [view]
all_inputs = {p: assumptions(p, fits, historical, horizon) for p in PRODUCT_DEFAULTS}
forecasts = {p: forecast_clab_v2(**args) for p, args in all_inputs.items()}
manual = {p: forecast_clab_v2(**assumptions(p, fits, False, horizon)) for p in selected}
df = sum((forecasts[p].drop(columns="month") for p in selected))
df.insert(0, "month", np.arange(1, horizon + 1))
baseline_revenue = sum(manual[p].revenue.sum() for p in selected)
st.caption(
    f"{view} · {horizon} months · {mode} · Synthetic history · Opening portfolio: $0"
)
last = df.iloc[-1]
gross, reserve, net = gross_reserve_net_display(
    last.ending_gross_clab, last.ending_reserve
)
cards = st.columns(4)
cards[0].metric(
    "Total revenue",
    _fmt_dollar_scaled(df.revenue.sum()),
    delta=(
        f"{_fmt_dollar_scaled(df.revenue.sum()-baseline_revenue)} vs manual"
        if historical
        else None
    ),
)
cards[1].metric("Total provision expense", _fmt_dollar_scaled(df.new_provisions.sum()))
cards[2].metric("Total net revenue", _fmt_dollar_scaled(df.net_revenue.sum()))
cards[3].metric("Ending gross CLAB", gross)
st.caption(
    f"Ending reserve {reserve} · Ending net CLAB {net} · Charge-offs use the reserve; they are not expensed twice.".replace(
        "$", r"\$"
    )
)

left, right = st.columns([1, 1.35])
with left:
    fig = go.Figure()
    for product in selected:
        args = all_inputs[product]
        ages = np.arange(0, max(args["term_months"], 24) + 1)
        prefix = f"driver_{product}_"
        manual_curve = cumulative_default_pct(
            ages,
            st.session_state[prefix + "days"] / 30,
            st.session_state[prefix + "rate"],
        )
        fitted = cumulative_default_pct(
            ages,
            fits[product]["midpoint_months"],
            fits[product]["total_default_rate_pct"],
        )
        for name, values, active in [
            ("Manual", manual_curve, not historical),
            ("Historical", fitted, historical),
        ]:
            fig.add_trace(
                go.Scatter(
                    x=ages,
                    y=values,
                    name=f"{product} · {name}" + (" (applied)" if active else ""),
                    line=dict(
                        color=PRODUCT_DEFAULTS[product]["color"],
                        width=3 if active else 1.5,
                        dash="solid" if active else "dot",
                    ),
                )
            )
    layout(fig, "Default-curve overlay", "Cumulative default (%)")
    fig.update_xaxes(title="Months on book")
    st.plotly_chart(fig, width="stretch")
    st.button(
        "Use manual assumptions" if historical else "Apply historical curve",
        on_click=switch_source,
        width="stretch",
    )
with right:
    fig = go.Figure()
    for col, label, color in [
        ("revenue", "Revenue", "#16a34a"),
        ("new_provisions", "Provision expense", "#ef4444"),
        ("net_revenue", "Net revenue", "#1e2761"),
    ]:
        fig.add_trace(
            go.Scatter(
                x=df.month, y=df[col], name=label, line=dict(color=color, width=3)
            )
        )
    fig.update_xaxes(title="Forecast month")
    st.plotly_chart(
        layout(fig, "Monthly revenue schedule", "$ / month"), width="stretch"
    )
    st.caption(
        "New loans earn from the following month. Lifetime expected losses are provisioned at origination."
    )

schedule, forecast, vintage = st.tabs(
    ["Monthly revenue", "Forecast table", "Vintage analysis"]
)
with schedule:
    st.subheader("Monthly revenue schedule")
    table(df[["month", "revenue", "new_provisions", "net_revenue"]])
with forecast:
    fig = go.Figure()
    for col, label, color in [
        ("ending_gross_clab", "Gross CLAB", "#2563eb"),
        ("net_clab", "Net CLAB", "#1e2761"),
        ("ending_reserve", "Reserve", "#d97706"),
    ]:
        fig.add_trace(
            go.Scatter(
                x=df.month, y=df[col], name=label, line=dict(color=color, width=2)
            )
        )
    st.plotly_chart(layout(fig, "Loan book and reserve", "$"), width="stretch")
    period = st.radio("Table period", ["Monthly", "Quarterly"], horizontal=True)
    table(df if period == "Monthly" else aggregate_to_quarterly(df))
    if period == "Quarterly" and horizon % 3:
        st.caption(
            "Only complete quarters are shown. Remaining months are included in the monthly schedule and totals."
        )
    st.download_button(
        "Download monthly forecast",
        df.to_csv(index=False),
        f"{view.lower()}-forecast.csv",
        "text/csv",
    )
    st.download_button(
        "Download assumptions",
        json.dumps({"curve_source": mode, "products": all_inputs}, indent=2),
        "assumptions.json",
        "application/json",
    )
with vintage:
    st.caption(
        f"{row_count:,} synthetic loan records → {len(triangle):,} observed cohort / age rows → 2 fitted curves. This is the forecast's existing historical dataset."
    )
    product = st.selectbox("Historical product", list(PRODUCT_DEFAULTS))
    pooled = pooled_default_curve(triangle, product)
    fig = go.Figure(
        go.Scatter(
            x=pooled.months_on_book,
            y=pooled.cumulative_default_pct,
            mode="lines+markers",
            name="Observed",
        )
    )
    fit = fits[product]
    fig.add_trace(
        go.Scatter(
            x=pooled.months_on_book,
            y=cumulative_default_pct(
                pooled.months_on_book.to_numpy(),
                fit["midpoint_months"],
                fit["total_default_rate_pct"],
            ),
            name="Fitted",
        )
    )
    st.plotly_chart(
        layout(fig, "Observed and fitted default curve", "Cumulative default (%)"),
        width="stretch",
    )
    pivot = triangle[triangle["product"] == product].pivot(
        index="origination_month", columns="months_on_book", values="cum_default_pct"
    )
    fig = go.Figure(
        go.Heatmap(
            z=pivot.values,
            x=pivot.columns,
            y=pivot.index,
            colorscale="Blues",
            hoverongaps=False,
            colorbar=dict(title="Default %"),
        )
    )
    st.plotly_chart(
        layout(fig, "Vintage triangle", "Origination month"), width="stretch"
    )
    st.caption(
        "Blank cells are unobserved ages, not zero defaults. The separate vintage_app.py retains the 2M-loan CreditFresh / MoneyKey pipeline; those products are not silently mapped into this forecast."
    )
with st.expander("Model assumptions"):
    for product in selected:
        args = all_inputs[product]
        share = cumulative_default_pct(
            args["term_months"], args["midpoint_months"], 1.0
        )
        if share < 0.95:
            st.warning(
                f"{product}: only {share:.0%} of the default curve falls within the loan term. Repaid loans cannot default, so realized losses are below the headline rate."
            )
    st.write(
        "The existing engine is unchanged: an empty opening book, level-payment amortization, no prepayments or recoveries, and annual yield also used as the contractual interest rate. Revenue equals opening gross CLAB less current charge-offs, multiplied by annual yield / 12. Net revenue equals revenue less new provisions. Historical fitting retains its fixed curve steepness and censoring methodology."
    )
