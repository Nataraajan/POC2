"""LendSight: driver-based CLAB forecast with an explicit opening portfolio."""

import json
from html import escape
import numpy as np
import pandas as pd
import plotly.graph_objects as go
import streamlit as st
from clab_forecast_engine_v2 import (
    forecast_clab_v2,
    cumulative_default_pct,
    aggregate_to_quarterly,
)
from dashboard_support import (
    PRODUCT_DEFAULTS,
    DOLLAR_COLS,
    load_vintage_data,
    _fmt_dollar_scaled,
)

st.set_page_config(
    page_title="LendSight | CLAB Forecast",
    layout="wide",
    initial_sidebar_state="expanded",
)
st.markdown(
    """<style>
.stApp{background:#f5f8fd;color:#12274b}
.block-container{padding:1.1rem 1.4rem 2rem;max-width:1900px}
header[data-testid="stHeader"]{height:0;background:transparent}
h1,h2,h3{color:#071c55;letter-spacing:-.025em}
h1{font-size:1.65rem!important;margin:0!important;padding:0!important}
h3{font-size:1.05rem!important;padding:0 0 .45rem!important}
[data-testid="stSidebar"]{background:linear-gradient(150deg,#102846,#0a1b34);width:205px!important;min-width:205px!important}
[data-testid="stSidebar"] *{color:#c6d8ef}
[data-testid="stSidebar"] .block-container{padding:1rem}
.brand{font-size:1.45rem;font-weight:750;color:white!important;margin-bottom:1.6rem}
.brand span{color:#00c18c!important}
.navitem{display:block;padding:13px 12px;margin:6px 0;border-radius:7px;text-decoration:none!important;font-size:.9rem;color:#c6d8ef!important}
.navitem.active{background:#1c457b;color:white!important;font-weight:650}
.side-note{font-size:.77rem;margin-top:3rem;padding:12px;border:1px solid #315074;border-radius:8px;line-height:1.6}
[data-testid="stVerticalBlockBorderWrapper"]>div{border-color:#e4edf8!important;border-radius:12px!important;background:white}
[data-testid="stMetric"]{background:white;border:1px solid #e0eaf7;border-radius:10px;padding:12px 14px;min-height:103px}
[data-testid="stMetricValue"]{font-size:1.65rem;color:#0b205b;font-weight:700}
[data-testid="stMetricLabel"]{font-size:.8rem}
[data-testid="stNumberInput"] input{font-size:.85rem;padding:7px 10px}
[data-testid="stNumberInputContainer"]{min-height:32px}
[data-testid="stWidgetLabel"] p{font-size:.78rem}
[data-testid="stCaptionContainer"] p{font-size:.78rem;color:#647694}
.badge{display:inline-block;background:#e2f7ed;color:#04824e;border-radius:20px;padding:7px 14px;font-size:.77rem;font-weight:650}
.note{background:#e4f8ef;color:#067c4a;padding:9px 12px;border-radius:7px;font-size:.8rem}
.kpi{border:1px solid #e1eaf8;border-radius:10px;padding:12px;background:white;min-height:98px}
.kpi-label{font-size:.78rem;color:#30456d}.kpi-value{font-size:1.6rem;font-weight:750;color:#0a225e;margin:3px 0}
.kpi-note{font-size:.72rem;color:#647694}.kpi.green{background:#f0fcf7;border-color:#d4f2e3}.kpi.green .kpi-value{color:#00a35b}
.kpi.red{background:#fff6f7;border-color:#ffe0e5}.kpi.red .kpi-value{color:#e92746}
div[data-testid="stHorizontalBlock"]{gap:.8rem}
div[data-testid="stVerticalBlock"]{gap:.45rem}
div[data-testid="stVerticalBlock"][data-test-scroll-behavior="normal"]{background:transparent}
div[data-testid="stVerticalBlockBorderWrapper"],div[data-testid="stLayoutWrapper"]:has(>div>div[data-testid="stVerticalBlock"][style*="border"]){background:white}
[data-testid="stCaptionContainer"]{color:#586d8f!important}
[data-testid="stSidebarUserContent"]{padding-top:0!important}
.st-key-driver_panel,.st-key-revenue_panel,.st-key-curve_panel,.st-key-schedule_panel{background:white!important;border-color:#e1eaf6!important;border-radius:12px!important}
[data-testid="stCaptionContainer"] p{color:#566a89!important}
@media(max-width:1100px){.kpi-value{font-size:1.2rem}.block-container{padding:1rem}.kpi{padding:9px}}
</style>""",
    unsafe_allow_html=True,
)


def reset():
    for key in list(st.session_state):
        if key.startswith("driver_"):
            del st.session_state[key]
    st.session_state["scenario"] = "Base"


def preset(name):
    for product in PRODUCT_DEFAULTS:
        p = f"driver_{product}_"
        d = PRODUCT_DEFAULTS[product]
        st.session_state[p + "growth"] = {"Base": 0.0, "Upside": 2.0, "Downside": -2.0}[
            name
        ]
        st.session_state[p + "approval"] = (
            d["approval_rate"] + {"Base": 0.0, "Upside": 3.0, "Downside": -3.0}[name]
        )
        st.session_state[p + "stress"] = {
            "Base": 0.0,
            "Upside": -20.0,
            "Downside": 20.0,
        }[name]
    st.session_state["scenario"] = name


def custom():
    st.session_state["scenario"] = "Custom"


def apply_historical():
    st.session_state["driver_source"] = "Historical vintage"


def initialize():
    for product, d in PRODUCT_DEFAULTS.items():
        p = f"driver_{product}_"
        values = dict(
            apps=d["applications"],
            approval=d["approval_rate"],
            size=int(d["avg_loan_size"]),
            yield_=d["annual_yield"],
            term=d["term_months"],
            days=d["days_to_default"],
            rate=d["total_default_rate"],
            growth=0.0,
            stress=0.0,
            opening=255_600_000.0 if product == "Short-Term" else 383_400_000.0,
            age=3 if product == "Short-Term" else 6,
            age_mix="Even balance by MOB (assumed)",
        )
        values["yield"] = values.pop("yield_")
        for field, value in values.items():
            st.session_state.setdefault(p + field, value)
        for m in range(12):
            st.session_state.setdefault(p + f"season_{m}", 1.0)
    # Keep values for widgets not rendered while another product is selected.
    for key in list(st.session_state):
        if key.startswith("driver_"):
            st.session_state[key] = st.session_state[key]


def args(product, historical):
    ss, p = st.session_state, f"driver_{product}_"
    rate = fits[product]["total_default_rate_pct"] if historical else ss[p + "rate"]
    return dict(
        monthly_applications_base=ss[p + "apps"],
        seasonality_pattern=[ss[p + f"season_{m}"] for m in range(12)],
        approval_rate_pct=ss[p + "approval"],
        avg_loan_size=ss[p + "size"],
        annual_yield_pct=ss[p + "yield"],
        term_months=ss[p + "term"],
        horizon_months=horizon,
        midpoint_months=(
            fits[product]["midpoint_months"] if historical else ss[p + "days"] / 30
        ),
        total_default_rate_pct=rate * (1 + ss[p + "stress"] / 100),
        opening_gross_clab=ss[p + "opening"],
        opening_age_months=(
            None
            if ss[p + "age_mix"] == "Even balance by MOB (assumed)"
            else ss[p + "age"]
        ),
        monthly_growth_pct=ss[p + "growth"],
    )


def chart(fig, ytitle):
    fig.update_layout(
        height=265,
        margin=dict(l=8, r=8, t=30, b=10),
        paper_bgcolor="white",
        plot_bgcolor="white",
        hovermode="x unified",
        legend=dict(orientation="h", y=1.18, font=dict(size=10)),
        font=dict(color="#617292", size=11),
        yaxis_title=ytitle,
        xaxis_title="Forecast month",
    )
    fig.update_yaxes(gridcolor="#edf2f8", zerolinecolor="#d8e1ef")
    return fig


LABELS = {
    "month": "Month",
    "quarter": "Quarter",
    "applications": "Applications",
    "originations": "Originations",
    "beginning_gross_clab": "Opening gross CLAB",
    "principal_repaid": "Principal repayments",
    "charge_offs": "Charge-offs",
    "ending_gross_clab": "Gross CLAB",
    "new_provisions": "Provision expense",
    "beginning_reserve": "Opening reserve",
    "ending_reserve": "Reserve",
    "net_clab": "Net CLAB",
    "revenue": "Revenue",
    "net_revenue": "Net revenue",
}


def table(frame):
    st.dataframe(
        frame.rename(columns=LABELS),
        hide_index=True,
        width="stretch",
        height=300,
        column_config={
            **{
                LABELS[c]: st.column_config.NumberColumn(format="$%,.0f")
                for c in DOLLAR_COLS
                if c in frame
            },
            "Approval %": st.column_config.NumberColumn(format="%.1f%%"),
            "Applications": st.column_config.NumberColumn(format="%,.0f"),
        },
    )


initialize()
row_count, triangle, fits = load_vintage_data()
with st.sidebar:
    st.markdown(
        '<div class="brand"><span>✦</span> LendSight</div><a class="navitem active" href="#forecasting">▥ &nbsp; Forecasting</a><a class="navitem" href="#monthly-forecast-schedule">▤ &nbsp; Monthly schedule</a><a class="navitem" href="#vintage-analysis">◈ &nbsp; Vintage analysis</a><a class="navitem" href="#model-assumptions">⚙ &nbsp; Model assumptions</a><div class="side-note">Planning prototype<br>Synthetic loan history<br>Illustrative opening portfolio</div>',
        unsafe_allow_html=True,
    )

st.markdown(
    '<h1 id="forecasting">CLAB Forecast — Driver-Based Revenue Model</h1>',
    unsafe_allow_html=True,
)
st.caption("Applications → Originations → CLAB → Charge-offs → Revenue")
toolbar = st.columns([1.2, 0.8, 0.65, 0.65, 0.8, 0.65, 1.5, 0.65])
view = toolbar[0].selectbox(
    "Portfolio", ["Combined"] + list(PRODUCT_DEFAULTS), key="portfolio"
)
horizon = toolbar[1].number_input("Horizon (months)", 6, 36, 24, key="driver_horizon")
for col, name in zip(toolbar[2:5], ["Base", "Upside", "Downside"]):
    col.button(
        name,
        on_click=preset,
        args=(name,),
        width="stretch",
        help="Sets growth, approval and credit stress; other drivers are retained.",
    )
toolbar[5].button("Reset", on_click=reset, width="stretch")
toolbar[6].markdown(
    f'<span class="badge">● {escape(st.session_state.get("scenario","Base"))} scenario · Live calculation</span>',
    unsafe_allow_html=True,
)
selected = list(PRODUCT_DEFAULTS) if view == "Combined" else [view]
focus = toolbar[7].number_input("KPI month", 1, horizon, 1, key=f"focus_{horizon}")
with st.container(border=True, key="driver_panel"):
    driver_title, driver_note, driver_product = st.columns([1, 2.4, 1])
    driver_title.subheader("Forecast Drivers")
    driver_note.caption(
        "$639M end-Q2 CLAB treated as gross performing loans. Initial 40% / 60% product split and age mix are assumptions."
    )
    edit = (
        driver_product.selectbox(
            "Edit product drivers",
            selected,
            key="edit_product",
            label_visibility="collapsed",
        )
        if view == "Combined"
        else view
    )
    p = f"driver_{edit}_"
    cols = st.columns([1, 1, 1, 1.2, 1.15])

    def number(col, label, field, minimum, maximum, step):
        return col.number_input(
            label, minimum, maximum, step=step, key=p + field, on_change=custom
        )

    with cols[0]:
        st.markdown("**◈ Volume Drivers**")
        number(st, "Applications / month", "apps", 0, 500000, 500)
        number(st, "Monthly growth (%)", "growth", -20.0, 20.0, 0.5)
        with st.expander("Seasonality · 12 months"):
            for m in range(12):
                number(st, f"Month {m+1} multiplier", f"season_{m}", 0.5, 1.5, 0.1)
    with cols[1]:
        st.markdown("**♧ Underwriting**")
        number(st, "Approval rate (%)", "approval", 0.0, 100.0, 1.0)
        number(st, "Average loan size ($)", "size", 100, 100000, 100)
        number(st, "Loan term (months)", "term", 1, 60, 1)
    with cols[2]:
        st.markdown("**◇ Yield & Pricing**")
        number(st, "Annual yield (%)", "yield", 0.0, 200.0, 1.0)
        st.caption("Yield also determines the contractual amortization schedule.")
        st.caption("Existing loans earn in month 1. New loans earn from month 2.")
    with cols[3]:
        st.markdown("**◒ Credit Curve**")
        mode = st.selectbox(
            "Default curve source",
            ["Manual assumptions", "Historical vintage"],
            key="driver_source",
        )
        historical = mode == "Historical vintage"
        number(st, "Default-rate stress (%)", "stress", -100.0, 100.0, 5.0)
        with st.expander("Manual curve assumptions"):
            st.number_input(
                "Lifetime default rate (%)",
                0.0,
                50.0,
                step=1.0,
                key=p + "rate",
                disabled=historical,
                on_change=custom,
            )
            st.number_input(
                "Days to default",
                1,
                365,
                key=p + "days",
                disabled=historical,
                on_change=custom,
            )
    with cols[4]:
        st.markdown("**▧ Opening Portfolio**")
        number(
            st, "Opening gross CLAB ($)", "opening", 0.0, 1_000_000_000.0, 1_000_000.0
        )
        st.selectbox(
            "Opening age mix",
            ["Even balance by MOB (assumed)", "Single cohort at specified MOB"],
            key=p + "age_mix",
            on_change=custom,
        )
        # A term reduction can invalidate an existing age. Clamp visibly before rendering.
        if st.session_state[p + "age"] >= st.session_state[p + "term"]:
            st.session_state[p + "age"] = st.session_state[p + "term"] - 1
            st.caption("Opening age adjusted to stay within the new loan term.")
        if st.session_state[p + "age_mix"] == "Single cohort at specified MOB":
            number(
                st, "Opening age (MOB)", "age", 0, st.session_state[p + "term"] - 1, 1
            )
        st.caption(
            "Opening reserve = remaining expected losses. New-loan provision: at origination."
        )

all_inputs = {product: args(product, historical) for product in PRODUCT_DEFAULTS}
forecasts = {product: forecast_clab_v2(**a) for product, a in all_inputs.items()}
df = sum((forecasts[product].drop(columns="month") for product in selected))
df.insert(0, "month", np.arange(1, horizon + 1))
current = df.iloc[focus - 1]
cards = st.columns(6)
for col, (field, label, tint) in zip(
    cards,
    [
        ("originations", "Originations", ""),
        ("ending_gross_clab", "Gross CLAB", ""),
        ("net_clab", "Net CLAB", ""),
        ("charge_offs", "Charge-offs", "red"),
        ("revenue", "Monthly Revenue", "green"),
        ("net_revenue", "Net Revenue", "green"),
    ],
):
    col.markdown(
        f'<div class="kpi {tint}"><div class="kpi-label">{label}</div><div class="kpi-value">{_fmt_dollar_scaled(current[field])}</div><div class="kpi-note">Forecast month {focus}</div></div>',
        unsafe_allow_html=True,
    )

left, right = st.columns([1.1, 1])
with left, st.container(border=True, key="revenue_panel"):
    st.subheader("Monthly Revenue Schedule")
    fig = go.Figure()
    for field, label, color in [
        ("revenue", "Revenue", "#00ad60"),
        ("net_revenue", "Net revenue", "#111f65"),
    ]:
        fig.add_trace(
            go.Scatter(
                x=df.month,
                y=df[field],
                name=label,
                line=dict(
                    color=color,
                    width=3,
                    dash="dash" if field == "net_revenue" else "solid",
                ),
            )
        )
    fig.add_trace(
        go.Bar(
            x=df.month,
            y=df.new_provisions,
            name="Provision expense",
            marker_color="#f34c60",
            opacity=0.7,
        )
    )
    st.plotly_chart(chart(fig, "$ / month"), width="stretch")
    opening = df.iloc[0]
    st.markdown(
        f'<div class="note">Month 1 earns on {_fmt_dollar_scaled(opening.beginning_gross_clab)} of opening loans, less charge-offs. Its existing reserve is carried forward.</div>',
        unsafe_allow_html=True,
    )
with right, st.container(border=True, key="curve_panel"):
    st.subheader("Default Curve Overlay")
    fig = go.Figure()
    for product in selected:
        hist = triangle[triangle["product"] == product]
        for i, (_, cohort) in enumerate(hist.groupby("origination_month")):
            fig.add_trace(
                go.Scatter(
                    x=cohort.months_on_book,
                    y=cohort.cum_default_pct,
                    mode="lines",
                    line=dict(color="rgba(224,147,147,.20)", width=1),
                    name="Individual vintages",
                    showlegend=i == 0 and product == selected[0],
                    hoverinfo="skip",
                )
            )
        ages = np.arange(max(all_inputs[product]["term_months"], 24) + 1)
        for hist_mode, name, color, dash in [
            (True, "Historical fitted", "#172468", "solid"),
            (False, "Manual", "#348ad2", "dash"),
        ]:
            a = args(product, hist_mode)
            fig.add_trace(
                go.Scatter(
                    x=ages,
                    y=cumulative_default_pct(
                        ages, a["midpoint_months"], a["total_default_rate_pct"]
                    ),
                    name=f"{product} · {name}",
                    line=dict(color=color, width=2.5, dash=dash),
                )
            )
    chart(fig, "Cumulative default %")
    fig.update_xaxes(title="Months on book (MOB)")
    st.plotly_chart(fig, width="stretch")
    st.caption(
        f"Applied: {mode} + product stress · {row_count:,} historical records · Censored vintage fit"
    )
    st.button(
        "Apply historical curve",
        on_click=apply_historical,
        disabled=historical,
        width="stretch",
    )

with st.container(border=True, key="schedule_panel"):
    st.markdown(
        '<h3 id="monthly-forecast-schedule">Monthly Forecast Schedule</h3>',
        unsafe_allow_html=True,
    )
    summary = df[
        [
            "month",
            "applications",
            "originations",
            "ending_gross_clab",
            "charge_offs",
            "ending_reserve",
            "revenue",
            "new_provisions",
            "net_revenue",
        ]
    ].copy()
    approved = sum(
        forecasts[product].originations / all_inputs[product]["avg_loan_size"]
        for product in selected
    )
    summary.insert(
        2,
        "Approval %",
        np.divide(
            approved,
            df.applications,
            out=np.zeros(len(df)),
            where=df.applications.to_numpy() != 0,
        )
        * 100,
    )
    table(summary)
    download, details = st.columns([1, 4])
    download.download_button(
        "Download forecast",
        df.to_csv(index=False),
        "clab-forecast.csv",
        "text/csv",
        width="stretch",
    )
    details.caption(
        f"Horizon revenue {_fmt_dollar_scaled(df.revenue.sum())} · Provision expense {_fmt_dollar_scaled(df.new_provisions.sum())} · Net revenue {_fmt_dollar_scaled(df.net_revenue.sum())}".replace(
            "$", r"\$"
        )
    )
    with st.expander("Full balance reconciliation & quarterly reporting"):
        period = st.radio("Table period", ["Monthly", "Quarterly"], horizontal=True)
        table(df if period == "Monthly" else aggregate_to_quarterly(df))
        if period == "Quarterly" and horizon % 3:
            st.caption(
                "Only complete quarters shown; monthly schedule includes the remaining months."
            )
        st.download_button(
            "Download assumptions",
            json.dumps(
                {
                    "source": mode,
                    "scenario": st.session_state.get("scenario", "Base"),
                    "products": all_inputs,
                },
                indent=2,
            ),
            "assumptions.json",
            "application/json",
        )

st.markdown('<h3 id="vintage-analysis">Vintage Analysis</h3>', unsafe_allow_html=True)
with st.expander("Historical cohort triangle"):
    product = st.selectbox("Historical product", list(PRODUCT_DEFAULTS))
    pivot = triangle[triangle["product"] == product].pivot(
        index="origination_month", columns="months_on_book", values="cum_default_pct"
    )
    st.plotly_chart(
        chart(
            go.Figure(
                go.Heatmap(
                    z=pivot.values,
                    x=pivot.columns,
                    y=pivot.index,
                    colorscale="Blues",
                    hoverongaps=False,
                )
            ),
            "Origination month",
        ),
        width="stretch",
    )
    st.caption(
        "Blank cells are unobserved ages. The separate CreditFresh / MoneyKey 2M-row pipeline remains in vintage_app.py; it is not the source for these forecast products."
    )
st.markdown('<h3 id="model-assumptions">Model Assumptions</h3>', unsafe_allow_html=True)
with st.expander("Opening book, provision timing & scenario definitions"):
    st.write(
        "The initial total opening CLAB is $639M at end-Q2, supplied by the user. The initial 40% Short-Term / 60% Installment allocation is illustrative. With age mix unknown, the default distributes each product's current balance evenly across MOB 0 through term minus 1. Alternatively, select a single cohort age. Remaining principal and default risk are conditional on survival to each age. Actual cohort data should replace these assumptions when available."
    )
    st.write(
        "Opening reserve is the remaining expected loss on the existing book. It is a beginning balance, not month-1 provision expense. Changing credit assumptions recalculates this illustrative opening reserve; no accounting catch-up adjustment against an actual booked reserve is modeled."
    )
    st.write(
        "Provision expense covers lifetime expected losses on new originations. Revenue = (opening gross CLAB − charge-offs) × annual yield / 12. New loans begin earning next month. Charge-offs reduce both gross CLAB and reserve, without a second P&L charge. Net revenue = revenue − new provisions. No prepayments or recoveries are modeled."
    )
    st.write(
        "Scenario buttons set growth, approval and default-rate stress; other assumptions are retained. Base: 0% growth / default approval / 0% stress. Upside: +2% monthly growth / +3 percentage points approval / −20% default rate. Downside: −2% growth / −3 percentage points approval / +20% default rate. Stress scales default probability, not loss severity."
    )
