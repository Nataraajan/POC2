"""LendSight: driver-based CLAB forecast with an explicit opening portfolio."""

import json
from html import escape
import numpy as np
import pandas as pd
import plotly.graph_objects as go
import streamlit as st
from excel_export import export_model
from vintage_overlay import render_overlay
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
.kpi-grid{display:grid;grid-template-columns:repeat(3,minmax(0,1fr));gap:14px;margin:12px 0 28px}.kpi{box-sizing:border-box;min-width:0;overflow-wrap:anywhere;border:1px solid #e1eaf8;border-radius:10px;padding:12px;background:white;min-height:98px}
.kpi-years{display:grid;grid-template-columns:1fr 1fr;gap:16px;margin-top:18px}.kpi-period+ .kpi-period{border-left:1px solid #dce5ef;padding-left:16px}.kpi-footer{border-top:1px solid #e3eaf3;margin-top:14px;padding-top:10px;font-size:.78rem;color:#465d7a}.kpi{padding:20px!important;box-shadow:0 4px 16px #10284606}.kpi.hero{background:#112c50;border-color:#112c50}.kpi.hero .kpi-label,.kpi.hero .kpi-value{color:white}.kpi.hero .kpi-note,.kpi.hero .kpi-footer{color:#c6d8ef}.kpi.hero .kpi-footer{border-color:#345071}.kpi-label{font-size:.78rem;color:#30456d}.kpi-value{font-size:1.6rem;font-weight:750;color:#0a225e;margin:3px 0}
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
@media(max-width:700px){.kpi-grid{grid-template-columns:repeat(2,minmax(0,1fr))}}
@media(max-width:1100px){.kpi-value{font-size:1.2rem}.block-container{padding:1rem}.kpi{padding:9px}}
</style>""",
    unsafe_allow_html=True,
)


def reset():
    st.session_state.pop("applied_overlay", None)
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
if st.session_state.get("applied_overlay"):
    fits = st.session_state["applied_overlay"]["fits"]
with st.sidebar:
    st.markdown(
        '<div class="brand"><span>✦</span> LendSight</div>', unsafe_allow_html=True
    )
    section = st.radio(
        "Navigation",
        ["Forecasting", "Monthly schedule", "Vintage overlay", "Vintage analysis", "Model assumptions"],
        key="navigation",
        label_visibility="collapsed",
    )
    st.caption(
        "Synthetic history. User-supplied opening CLAB; assumed product split and age mix."
    )
st.session_state.setdefault("driver_source", "Manual assumptions")
mode = st.session_state["driver_source"]
historical = mode == "Historical vintage"

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
focus = toolbar[7].number_input("Detail month", 1, horizon, 1, key=f"focus_{horizon}")
if section == "Forecasting":
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
                st,
                "Opening gross CLAB ($)",
                "opening",
                0.0,
                1_000_000_000.0,
                1_000_000.0,
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
                    st,
                    "Opening age (MOB)",
                    "age",
                    0,
                    st.session_state[p + "term"] - 1,
                    1,
                )
            st.caption(
                "Opening reserve = remaining expected losses. New-loan provision: at origination."
            )

all_inputs = {product: args(product, historical) for product in PRODUCT_DEFAULTS}
forecasts = {product: forecast_clab_v2(**a) for product, a in all_inputs.items()}
df = sum((forecasts[product].drop(columns="month") for product in selected))
df.insert(0, "month", np.arange(1, horizon + 1))
current = df.iloc[focus - 1]
manual_forecasts = {
    product: forecast_clab_v2(**args(product, False)) for product in selected
}
manual_revenue = sum(f.revenue.sum() for f in manual_forecasts.values())
manual_provision = sum(f.new_provisions.sum() for f in manual_forecasts.values())
st.success(
    f"Applied to forecast: {mode.upper()} · Rates and timing below feed provisions, charge-offs, balances and revenue."
)
if historical and st.session_state.get("applied_overlay"):
    st.info("Applied vintage experiment: " + " · ".join(f"{p} ← {v}" for p,v in st.session_state["applied_overlay"]["mapping"].items()))
if historical:
    st.caption(
        f"Historical vs current manual assumptions, same operating drivers: horizon revenue change {_fmt_dollar_scaled(df.revenue.sum()-manual_revenue)}; provision change {_fmt_dollar_scaled(df.new_provisions.sum()-manual_provision)}. Opening reserve is recalculated in both scenarios.".replace(
            "$", r"\$"
        )
    )
if section == "Forecasting":
    st.subheader("Annual forecast KPIs")
    cards = []
    for field, label, tint, balance in [
        ("revenue", "Revenue", "hero", False),
        ("new_provisions", "PLL / provision expense", "red", False),
        ("net_revenue", "Net Revenue", "green", False),
        ("originations", "Originations", "", False),
        ("ending_gross_clab", "Gross CLAB", "", True),
        ("net_clab", "Net CLAB", "", True),
    ]:
        values = []
        for year in (1, 2):
            period = df[(df.month > (year-1)*12) & (df.month <= year*12)]
            complete = len(period) == 12
            value = _fmt_dollar_scaled(period[field].iloc[-1] if balance else period[field].sum()) if complete else "—"
            note = "year-end" if balance else "annual total"
            if not complete:
                note = "requires " + str(year*12) + " forecast months"
            values.append(f'<div class="kpi-period"><div class="kpi-note">Year {year} · {note}</div><div class="kpi-value">{value}</div></div>')
        yearly = [df[(df.month > j*12) & (df.month <= (j+1)*12)] for j in range(2)]
        if field == "new_provisions":
            ratios = [f"{x.new_provisions.sum()/x.revenue.sum():.1%}" if len(x)==12 and x.revenue.sum()!=0 else "—" for x in yearly]
            footer = f"PLL / revenue: Y1 {ratios[0]} · Y2 {ratios[1]}<br>Reported benchmark: 45–50% · calibration pending"
        elif all(len(x)==12 for x in yearly):
            totals = [x[field].iloc[-1] if balance else x[field].sum() for x in yearly]
            change = f"{(totals[1]/totals[0]-1)*100:+.1f}%" if totals[0] else "—"
            footer = f"Year 2 vs Year 1: {change}" + (" · closing balance" if balance else " · annual total")
        else:
            footer = "Extend horizon to 24 months for annual comparison"
        cards.append(f'<div class="kpi {tint}"><div class="kpi-label">{label}</div><div class="kpi-years">{"".join(values)}</div><div class="kpi-footer">{footer}</div></div>')
    st.markdown('<div class="kpi-grid">' + ''.join(cards) + '</div>', unsafe_allow_html=True)
    st.caption("Year 1 = forecast months 1–12; Year 2 = months 13–24. Balances are year-end snapshots; all other KPIs are annual totals.")

    left, right = st.columns([1.1, 1])
    with left, st.container(border=True, key="revenue_panel"):
        st.subheader("Monthly Revenue Trend")
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
        runoff = current.principal_repaid + current.charge_offs
        st.caption(
            f"Month {focus}: new originations {_fmt_dollar_scaled(current.originations)} vs repayments {_fmt_dollar_scaled(current.principal_repaid)} and charge-offs {_fmt_dollar_scaled(current.charge_offs)}. Gross CLAB {'falls' if runoff>current.originations else 'rises'} by {_fmt_dollar_scaled(abs(current.originations-runoff))}. Revenue follows the earning balance, not the opening $639M forever.".replace(
                "$", r"\$"
            )
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
                        name="Original history (reference only)",
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
                        hovertemplate=(f"<b>{product} · {name}</b><br>" + ("APPLIED" if hist_mode == historical else "Comparison only") + "<br>MOB %{x:.0f}<br>Cumulative default: %{y:.2f}%<extra></extra>"),
                        name=f"{product} · {name}"
                        + (
                            " — APPLIED" if hist_mode == historical else " — comparison"
                        ),
                        line=dict(
                            color=color,
                            width=4 if hist_mode == historical else 1.5,
                            dash="solid" if hist_mode == historical else "dot",
                        ),
                    )
                )
        chart(fig, "Cumulative default %")
        fig.update_xaxes(title="Months on book (MOB)", dtick=3)
        fig.update_layout(height=380, hovermode="closest", hoverlabel=dict(namelength=-1, bgcolor="white", font_size=12), margin=dict(l=15,r=15,t=15,b=120), legend=dict(orientation="h", y=-.3, yanchor="top", x=0))
        fig.update_yaxes(ticksuffix="%")
        st.plotly_chart(fig, width="stretch")
        st.caption("Charge-offs = incremental defaults × principal still owed, summed across cohorts. The model assumes full loss of that balance (no recoveries). PLL is lifetime expected loss on new originations, booked upfront; subsequent charge-offs use the reserve and are not a second expense.")
        st.caption(
            (f"Applied: mapped 100,000-loan experiment + product stress. Faint vintages are original history for reference." if historical and st.session_state.get("applied_overlay") else f"Applied: {mode} + product stress · {row_count:,} synthetic historical records · Original-loan-amount-weighted default curve")
        )
        for product in selected:
            a = all_inputs[product]
            st.caption(
                f"{product}: applied lifetime default {a['total_default_rate_pct']:.2f}%; midpoint {a['midpoint_months']:.2f} MOB (including stress)."
            )
        st.button(
            "Apply historical curve",
            on_click=apply_historical,
            disabled=historical,
            width="stretch",
        )

if section in ("Forecasting", "Monthly schedule"):
    with st.container(border=True, key="schedule_panel"):
        st.markdown(
            '<h3 id="monthly-forecast-schedule">Monthly Revenue & Forecast Schedule</h3>',
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
        st.caption("Approval is application-weighted across the selected portfolio. " + " · ".join(f"{p}: {all_inputs[p]['approval_rate_pct']:.1f}%" for p in selected) + ". Driver inputs edit one product at a time.")
        with st.expander("How reserve and charge-offs reconcile"):
            st.write("Reserve = beginning reserve + PLL on new originations − charge-offs. Opening reserve covers future expected losses on the existing book and is not booked again as expense.")
            st.write("Charge-offs = original-equivalent cohort exposure × incremental default probability × scheduled principal fraction before default. Sum across cohorts. LGD is 100%; no recoveries. Charge-offs reduce gross loans and reserve, not net revenue a second time.")
        horizontal = summary.set_index("month").rename(columns=LABELS).T
        horizontal.columns = [f"Month {m}" for m in summary.month]
        horizontal.index.name = "Metric"
        horizontal = horizontal.astype(float)
        money_rows = [r for r in horizontal.index if r not in ("Applications", "Approval %")]
        horizontal.loc[money_rows] /= 1_000_000
        st.caption("Months run left to right · financial amounts in $ millions · applications are counts · approval is percent. Scroll horizontally for later months.")
        st.dataframe(horizontal.style.format("{:,.2f}").format("{:,.0f}", subset=pd.IndexSlice[["Applications"], :]).format("{:.1f}%", subset=pd.IndexSlice[["Approval %"], :]), width="stretch", height=390)
        download, details = st.columns([1, 4])
        snapshot = {
            "source": mode,
            "scenario": st.session_state.get("scenario", "Base"),
            "view": view,
            "products": {
                product: {
                    "active": all_inputs[product],
                    "manual_rate_pct": st.session_state[f"driver_{product}_rate"],
                    "manual_midpoint": st.session_state[f"driver_{product}_days"] / 30,
                    "historical_rate_pct": fits[product]["total_default_rate_pct"],
                    "historical_midpoint": fits[product]["midpoint_months"],
                    "stress_pct": st.session_state[f"driver_{product}_stress"],
                }
                for product in PRODUCT_DEFAULTS
            },
        }
        download.download_button(
            "Excel model",
            export_model(snapshot),
            "CLAB-revenue-model.xlsx",
            "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            width="stretch",
        )
        st.caption(
            "Excel includes editable blue inputs, linked formulas, full cohort calculations and balance checks. 36-month build; horizon totals match the selected forecast. Excel recalculates when opened."
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

if section == "Vintage analysis":
    st.markdown(
        '<h3 id="vintage-analysis">Vintage Analysis</h3>', unsafe_allow_html=True
    )
    with st.expander("Historical cohort triangle", expanded=True):
        product = st.selectbox("Historical product", list(PRODUCT_DEFAULTS))
        pivot = triangle[triangle["product"] == product].pivot(
            index="origination_month",
            columns="months_on_book",
            values="cum_default_pct",
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
if section == "Vintage overlay":
    render_overlay(all_inputs)

if section == "Model assumptions":
    st.markdown(
        '<h3 id="model-assumptions">Model Assumptions</h3>', unsafe_allow_html=True
    )
    with st.expander(
        "Opening book, provision timing & scenario definitions", expanded=True
    ):
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
