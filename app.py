"""LendSight: driver-based CLAB forecast with an explicit opening portfolio."""
from segments import SEGMENTS
from propel_reference import OPENING_CLAB, OPENING_SHARES, MONTHLY_GROWTH_PCT, MONTHLY_FUNDING, CLAB_GROWTH, HISTORY, SOURCE_LATEST, reference_path

import json
from html import escape
import numpy as np
import pandas as pd
import streamlit as st
from product_forecast import default_product_curves, segment_forecasts, combine
from curve_model import SYNTHETIC, MANUAL
from scenario_tools import preset_values, metrics
from curve_controls import render_controls, render_curve_comparison
from clab_forecast_engine_v2 import (
    forecast_clab_v2,
    cumulative_default_pct,
    aggregate_to_quarterly,
)
from dashboard_support import (
    PRODUCT_DEFAULTS,
    DOLLAR_COLS,
    _fmt_dollar_scaled,
)

st.set_page_config(
    page_title="LendSight | CLAB Forecast",
    page_icon="https://cdn.propelholdings.com/web/assets/logos/icon-blue.svg",
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
/* Palette sampled from propelholdings.com: blue #0078D9, slate #263A50. */
.stApp{background:#f5f7fa;color:#263a50}
h1,h2,h3{color:#263a50}
[data-testid="stSidebar"]{background:#263a50}
.brand span{color:#68b8ff!important}
.st-key-navigation [role="radiogroup"],.st-key-navigation [role="radiogroup"]>div{width:100%!important}
.st-key-navigation [role="radiogroup"] label{display:flex!important;box-sizing:border-box;width:100%!important;min-height:62px;padding:12px 14px!important;margin:4px 0!important;border:1px solid #506277;border-radius:8px;background:#30465e;cursor:pointer;transition:background .15s}
.st-key-navigation [role="radiogroup"] label > div{width:100%}
.st-key-navigation [role="radiogroup"] label p{font-weight:550}
.st-key-navigation [role="radiogroup"] label > div > div:first-child:not([data-testid]){display:none!important}
.st-key-navigation [role="radiogroup"] label:focus-within{outline:2px solid #a8d8ff;outline-offset:2px}
.st-key-navigation [role="radiogroup"] label:hover{background:#344e69}
.st-key-navigation [role="radiogroup"] label:has(input:checked){background:#ffffff!important;box-shadow:0 2px 8px #14253626}
.st-key-navigation [role="radiogroup"] label:has(input:checked) p{color:#263a50!important;font-weight:700}
.st-key-forecast_toolbar button{height:42px!important;min-height:42px!important;border-radius:8px!important;padding:6px 12px!important;border-color:#cbd5df!important}
.st-key-forecast_toolbar button p{white-space:nowrap;font-size:.82rem!important}
.st-key-forecast_toolbar button:hover{border-color:#0078d9!important;color:#0078d9!important;background:#edf6ff!important}
.badge{background:#0078d9;color:white;border-radius:8px;padding:9px 16px}
.kpi.hero{background:#263a50;border-color:#263a50}
.kpi-value{color:#263a50}
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
        values = preset_values(name, product)
        st.session_state[p + "growth"] = values["monthly_growth_pct"]
        st.session_state[p + "approval"] = values["approval_rate_pct"]
    st.session_state["scenario"] = name


def custom():
    st.session_state["scenario"] = "Custom"


def apply_historical():
    st.session_state["driver_source"] = SYNTHETIC


def initialize():
    # Carry open sessions forward after the category label change.
    for old in list(st.session_state):
        if "Short-Term" in old:
            new = old.replace("Short-Term", "Line of Credit")
            st.session_state.setdefault(new, st.session_state[old])
            del st.session_state[old]
    for key in ("portfolio", "edit_product", "curve_segment", "triangle_product"):
        value = st.session_state.get(key)
        if isinstance(value, str) and "Short-Term" in value:
            st.session_state[key] = value.replace("Short-Term", "Line of Credit")
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
            growth=MONTHLY_GROWTH_PCT,
            stress=0.0,
            opening=OPENING_CLAB * OPENING_SHARES[product],
            age=3 if product == "Line of Credit" else 6,
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
    rate = ss[p + "rate"]  # overwritten by exact segment risk before forecasting
    return dict(
        monthly_applications_base=ss[p + "apps"],
        seasonality_pattern=[ss[p + f"season_{m}"] for m in range(12)],
        approval_rate_pct=ss[p + "approval"],
        avg_loan_size=ss[p + "size"],
        annual_yield_pct=ss[p + "yield"],
        term_months=ss[p + "term"],
        horizon_months=horizon,
        midpoint_months=(
            ss[p + "days"] / 30
        ),
        total_default_rate_pct=rate,
        opening_gross_clab=ss[p + "opening"],
        opening_age_months=(
            None
            if ss[p + "age_mix"] == "Even balance by MOB (assumed)"
            else ss[p + "age"]
        ),
        monthly_growth_pct=ss[p + "growth"],
    )


@st.cache_data(show_spinner=False, max_entries=64)
def cached_segment_forecasts(inputs, share, risks, curve_settings):
    """Cache pure forecasts; all drivers, horizon, mix and curves are hashed."""
    return segment_forecasts(inputs, share, risks)


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


def render_forecast_charts(df, current, focus, product_risks, product_fits):
    if st.toggle("Show revenue chart", value=False, key="show_revenue_chart"):
        import plotly.graph_objects as go
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
            f"Month {focus}: new originations {_fmt_dollar_scaled(current.originations)} vs repayments {_fmt_dollar_scaled(current.principal_repaid)} and charge-offs {_fmt_dollar_scaled(current.charge_offs)}. Gross CLAB {'falls' if runoff>current.originations else 'rises'} by {_fmt_dollar_scaled(abs(current.originations-runoff))}. Revenue follows the earning balance. Opening age assumptions affect the initial runoff.".replace(
                "$", r"\$"
            )
        )
    if st.toggle("Show applied curve chart", value=False, key="show_applied_chart"):
        st.subheader("Applied curves vs synthetic history")
        render_curve_comparison(product_risks, product_fits)
        st.caption("Charge-offs use incremental defaults × principal still owed. PLL is the expected lifetime principal loss on new originations, booked upfront. Terms remain 12/24 months.")


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
# Segment payment curves are the sole historical input for the forecast.

if "navigation" not in st.session_state and st.query_params.get("page") == "vintage":
    st.session_state["navigation"] = "Vintage Analysis & Overlay"
if st.session_state.get("navigation") == "Monthly schedule":
    st.session_state["navigation"] = "Forecasting"
if st.session_state.get("navigation") in ("Vintage analysis", "Vintage overlay"):
    st.session_state["navigation"] = "Vintage Analysis & Overlay"
with st.sidebar:
    st.markdown(
        '<div class="brand"><img src="https://cdn.propelholdings.com/web/assets/logos/icon-blue.svg" alt="Propel" style="width:30px;height:30px;padding:4px;background:white;border-radius:7px;vertical-align:middle;margin-right:7px">LendSight</div>', unsafe_allow_html=True
    )
    section = st.radio(
        "Navigation",
        ["Forecasting", "Vintage Analysis & Overlay", "Model assumptions"],
        key="navigation",
        label_visibility="collapsed",
    )
    st.caption(
        "Synthetic credit curves. Q2 2026 reported volume anchors; assumed product split and age mix."
    )
st.session_state.setdefault("driver_source", SYNTHETIC)
mode = st.session_state["driver_source"]
historical = mode == SYNTHETIC

st.markdown(
    '<h1 id="forecasting">' + ("Vintage Analysis & Overlay" if section == "Vintage Analysis & Overlay" else "Driver-Based Revenue Model") + '</h1>',
    unsafe_allow_html=True,
)
st.caption("Synthetic history → original curves → editable assumptions → forecast" if section == "Vintage Analysis & Overlay" else "Applications → Originations → CLAB → Charge-offs → Revenue")
with st.container(key="forecast_toolbar"):
    toolbar = st.columns([1.2, .8, .8, .8, .8, 1.25, .8, .8])
view = toolbar[0].selectbox(
    "Loan-type view", ["Combined"] + list(PRODUCT_DEFAULTS), key="portfolio"
)
horizon = toolbar[1].number_input("Horizon (months)", 6, 36, 24, key="driver_horizon")
for col, name in zip(toolbar[2:5], ["Base", "Upside", "Downside"]):
    col.button(
        name,
        key="scenario_" + name,
        on_click=preset,
        args=(name,),
        width="stretch",
        help="Base uses Q2 2026 funded-volume growth and fitted conversion. Upside/downside vary monthly growth by 1 percentage point and conversion by 3 points. Credit assumptions are retained.",
    )
def toggle_comparison():
    st.session_state["compare_scenarios"] = True


toolbar[5].button("Compare scenarios", key="compare_scenarios_button", on_click=toggle_comparison, width="stretch")
toolbar[6].button("Reset", on_click=reset, width="stretch")
selected = list(PRODUCT_DEFAULTS) if view == "Combined" else [view]
st.session_state.setdefault("driver_creditfresh_mix", 80.0)
mix_left, mix_right = st.columns([1, 3])
cf_mix = mix_left.number_input("CreditFresh share (%)", 0.0, 100.0, step=1.0, key="driver_creditfresh_mix", on_change=custom) / 100
mix_right.caption(f"MoneyKey share: {1-cf_mix:.0%}. Editable product allocation applies to opening CLAB and originations within each loan type. This hypothetical POC assigns both loan types to each brand; it does not represent their actual product catalogue. Volume is allocated before applying each segment’s own risk curve; pricing and approval remain loan-type assumptions.")
product_fits = default_product_curves()
mode, curve_settings, curves_by_source = render_controls(
    product_fits, expanded=section == "Vintage Analysis & Overlay", on_change=custom)
historical = mode == SYNTHETIC
product_risks = curves_by_source[mode]
manual_product_risks = curves_by_source[MANUAL]
focus = toolbar[7].number_input("Detail month", 1, horizon, 1, key=f"focus_{horizon}")
def opening_allocation_changed():
    total = st.session_state["driver_opening_total_m"] * 1e6
    share = st.session_state["driver_line_of_credit_share"] / 100
    st.session_state["driver_Line of Credit_opening"] = total * share
    st.session_state["driver_Installment_opening"] = total * (1-share)
    custom()


def restore_opening_split():
    st.session_state["driver_line_of_credit_share"] = 40.0
    opening_allocation_changed()


def current_ai_context(inputs, monthly=None):
    return dict(inputs=inputs, share=cf_mix, selected=selected, source=mode,
                settings=curve_settings[mode], empirical=product_fits,
                scenario=st.session_state.get("scenario", "Base"), monthly=monthly)


def highlight_scenario_controls():
    # Render inside the results fragment so a driver edit clears the preset colour.
    active = st.session_state.get("scenario", "Base")
    css = []
    for name in ("Base", "Upside", "Downside"):
        selected = active == name
        css.append(f".st-key-scenario_{name} button {{background:{'#0078d9' if selected else 'white'}!important;color:{'white' if selected else '#263a50'}!important;border-color:{'#0078d9' if selected else '#cbd5df'}!important}}")
        css.append(f".st-key-scenario_{name} button p {{color:{'white' if selected else '#263a50'}!important;font-weight:{700 if selected else 400}}}")
    if st.session_state.get("compare_scenarios", False):
        css.append(".st-key-compare_scenarios_button button{background:#e1f1ff!important;border-color:#0078d9!important}")
    st.markdown("<style>" + "".join(css) + "</style>", unsafe_allow_html=True)


@st.dialog("Scenario comparison", width="large")
def show_scenario_comparison():
    all_inputs = {k: args(k, historical) for k in PRODUCT_DEFAULTS}
    parts = cached_segment_forecasts(all_inputs, cf_mix, product_risks, curve_settings[mode])
    df = combine(parts[b][k] for b in parts for k in selected)
    st.caption("Same current allocation, curves, yields and opening ages. Presets change application growth and approval only. Values in USD millions; flows cover the selected horizon.")
    rows = [{"Scenario": "Current · " + st.session_state.get("scenario", "Base"),
             **{k: v/1e6 for k, v in metrics(df).items()}}]
    for name in ("Base", "Upside", "Downside"):
        trial = {kind: dict(values, **preset_values(name, kind)) for kind, values in all_inputs.items()}
        parts = cached_segment_forecasts(trial, cf_mix, product_risks, curve_settings[mode])
        result = combine(parts[b][k] for b in parts for k in selected)
        rows.append({"Scenario": name, **{k: v/1e6 for k, v in metrics(result).items()}})
    st.table(pd.DataFrame(rows).set_index("Scenario").style.format("{:,.2f}"))


@st.fragment
def render_driver_panel_and_forecast():
    highlight_scenario_controls()
    # Preserve drivers for the loan type hidden during a fragment-only rerun.
    for key in list(st.session_state):
        if any(key.startswith(f"driver_{product}_") for product in PRODUCT_DEFAULTS):
            st.session_state[key] = st.session_state[key]
    if section in ("Forecasting", "Model assumptions"):
        total = sum(st.session_state[f"driver_{k}_opening"] for k in PRODUCT_DEFAULTS)
        st.session_state["driver_opening_total_m"] = total / 1e6
        st.session_state["driver_line_of_credit_share"] = (100 * st.session_state["driver_Line of Credit_opening"] / total if total else 40.0)
        with st.expander("Opening portfolio allocation", expanded=True):
            a, b, c = st.columns([1, 2, 1])
            a.number_input("Total opening CLAB ($M)", 0.0, None, step=1.0,
                           key="driver_opening_total_m", on_change=opening_allocation_changed)
            b.slider("Line of Credit share of opening CLAB (%)", 0.0, 100.0, step=1.0,
                     key="driver_line_of_credit_share", on_change=opening_allocation_changed)
            c.button("40 / 60 preset", key="restore_opening_split", on_click=restore_opening_split)
            short = st.session_state["driver_line_of_credit_share"]
            st.caption(f"Line of Credit {short:.1f}% = ${total*short/100/1e6:,.2f}M · Installment {100-short:.1f}% = ${total*(1-short/100)/1e6:,.2f}M. Splits the existing book only; changing the split preserves its total.")
    if section == "Forecasting":
        with st.container(border=True, key="driver_panel"):
            driver_title, driver_note, driver_product = st.columns([1, 2.4, 1])
            driver_title.subheader("Forecast Drivers")
            driver_note.caption(
                "Opening CLAB allocation and age mix are editable assumptions. New lending is controlled separately by applications and approvals."
            )
            edit = (
                driver_product.selectbox(
                    "Edit loan-type drivers",
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
                st.caption("Preset approval is an effective funding conversion, fitted to reported dollars; not a disclosed approval rate.")
                number(st, "Average loan size ($)", "size", 100, 100000, 100)
                st.number_input("Synthetic curve window (months)", 1, 60, step=1, key=p + "term", disabled=True)
                st.caption("12/24 months match the synthetic history. The 12-month window is not a contractual line-of-credit maturity; revolving redraws are not yet modeled.")
            with cols[2]:
                st.markdown("**◇ Yield & Pricing**")
                number(st, "Annual yield (%)", "yield", 0.0, 200.0, 1.0)
                st.caption("Yield also determines the contractual amortization schedule.")
                st.caption("Existing loans earn in month 1. New loans earn from month 2.")
            with cols[3]:
                st.markdown("**◒ Credit Curve**")
                st.write(mode)
                st.caption("Edit default rates and timing in Default & payoff assumptions above. Review original and adjusted curves in Vintage Analysis & Overlay.")
            with cols[4]:
                st.markdown("**▧ Opening Portfolio**")
                st.session_state[p + "opening_m"] = st.session_state[p + "opening"] / 1_000_000
                def update_opening():
                    st.session_state[p + "opening"] = st.session_state[p + "opening_m"] * 1_000_000
                    custom()
                st.number_input("Opening gross CLAB ($M)", 0.0, None, step=1.0,
                                format="%.2f", key=p + "opening_m", on_change=update_opening)
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
    segments = cached_segment_forecasts(all_inputs, cf_mix, product_risks, curve_settings[mode])
    forecasts = {kind: combine(segments[brand][kind] for brand in segments) for kind in all_inputs}
    brand_forecasts = {brand: combine(parts[kind] for kind in selected) for brand, parts in segments.items()}
    df = combine(brand_forecasts.values())
    current = df.iloc[focus - 1]
    st.session_state["ai_context"] = current_ai_context(all_inputs, df.to_dict(orient="records"))
    st.success(
        f"Applied to forecast: {mode.upper()} · Rates and timing below feed provisions, charge-offs, balances and revenue."
    )
    if historical and st.toggle("Compare with manual assumptions", value=False, key="show_manual_comparison"):
        manual_segments = cached_segment_forecasts(all_inputs, cf_mix, manual_product_risks, curve_settings[MANUAL])
        manual_revenue = sum(manual_segments[b][k].revenue.sum() for b in manual_segments for k in selected)
        manual_provision = sum(manual_segments[b][k].new_provisions.sum() for b in manual_segments for k in selected)
        st.caption(
            f"Synthetic vintage with adjustments vs current manual assumptions, same operating drivers: horizon revenue change {_fmt_dollar_scaled(df.revenue.sum()-manual_revenue)}; provision change {_fmt_dollar_scaled(df.new_provisions.sum()-manual_provision)}. Opening reserve is recalculated in both scenarios.".replace(
                "$", r"\$"
            )
        )
    if section in ("Forecasting", "Model assumptions"):
        with st.expander("Propel reported results and preset basis", expanded=False):
            st.caption("USD. FY2024 and FY2025 are full years; Q2 2026 is three months. Latest available quarter as reviewed September 30, 2026.")
            st.table(pd.DataFrame([{
                "Period": r["period"], "Ending CLAB ($M)": round(r["clab"]/1e6, 2),
                "CLAB YoY (%)": round((r["clab"]/r["prior_clab"]-1)*100, 2),
                "Funded in period ($M)": round(r["originations"]/1e6, 2),
                "Funding YoY (%)": round((r["originations"]/r["prior_originations"]-1)*100, 2),
                "Revenue in period ($M)": round(r["revenue"]/1e6, 2),
            } for r in HISTORY]))
            st.write(f"Base opening CLAB: ${OPENING_CLAB/1e6:,.3f}M. Starting monthly funding: ${MONTHLY_FUNDING/1e6:,.3f}M (Q2 average). Monthly volume growth: {MONTHLY_GROWTH_PCT:.4f}% (same-quarter YoY funding growth compounded monthly).")
            st.write("125,000 applications, the application/product splits and ticket sizes remain assumptions. Effective conversion is fitted to funded dollars; it is not Propel's disclosed approval rate. Repeat borrowing and line-of-credit redraws are approximated as new synthetic cohorts. Seasonality stays flat.")
            st.write("Reported CLAB covers more programs than this four-segment POC. The reported revenue yield also includes fee income and is not substituted for a contractual interest rate. Synthetic losses, repayments and opening ages are not calibrated to Propel.")
            if view == "Combined":
                comparison = reference_path(horizon)[-1]
                st.write(f"At month {horizon}, continuing historical CLAB growth of {CLAB_GROWTH:.2%} annually gives a reference balance of ${comparison/1e6:,.2f}M. The current model projects ${df.ending_gross_clab.iloc[-1]/1e6:,.2f}M: a gap of ${(df.ending_gross_clab.iloc[-1]-comparison)/1e6:,.2f}M. The reference is not forced into the forecast.")
            else:
                st.caption("Select Combined to compare model CLAB with the company-wide reference.")
            st.markdown("Sources: " + " · ".join(f"[{r['period']} MD&A]({r['source']})" for r in HISTORY))


    if section == "Forecasting":
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
            for product, share in [("CreditFresh", cf_mix), ("MoneyKey", 1-cf_mix)]:
                summary.insert(summary.columns.get_loc("revenue"), f"{product} revenue", brand_forecasts[product].revenue)
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
                "creditfresh_share": cf_mix,
                "segment_risks": product_risks,
                "manual_segment_risks": manual_product_risks,
                "historical_segment_risks": product_fits,
                "source": mode,
                "curve_settings": curve_settings,
                "scenario": st.session_state.get("scenario", "Base"),
                "public_reference": {"as_of": "2026-06-30", "source": SOURCE_LATEST, "opening_clab_usd": OPENING_CLAB, "monthly_funding_usd": MONTHLY_FUNDING, "monthly_volume_growth_pct": MONTHLY_GROWTH_PCT, "clab_growth_yoy": CLAB_GROWTH},
                "view": view,
                "products": {
                    product: {
                        "active": all_inputs[product],
                        "manual_rate_pct": st.session_state[f"driver_{product}_rate"],
                        "manual_midpoint": st.session_state[f"driver_{product}_days"] / 30,
                        "historical_rate_pct": st.session_state[f"driver_{product}_rate"],
                        "historical_midpoint": st.session_state[f"driver_{product}_days"] / 30,
                        "stress_pct": st.session_state[f"driver_{product}_stress"],
                    }
                    for product in PRODUCT_DEFAULTS
                },
            }
            # Include every exported assumption, including inactive-source controls.
            snapshot_key = json.dumps(snapshot, sort_keys=True)
            prepared = st.session_state.get("prepared_excel")
            if prepared is not None and prepared["snapshot_key"] != snapshot_key:
                del st.session_state["prepared_excel"]
                prepared = None
            if prepared is None:
                if download.button("Prepare Excel model", key="prepare_excel", width="stretch"):
                    with st.spinner("Preparing Excel model..."):
                        from excel_export import export_model
                        prepared = {"snapshot_key": snapshot_key, "data": export_model(snapshot)}
                        st.session_state["prepared_excel"] = prepared
            if prepared is not None:
                download.download_button(
                    "Download Excel model",
                    prepared["data"],
                    "CLAB-revenue-model.xlsx",
                    "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                    on_click="ignore",
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
                        snapshot,
                        indent=2,
                    ),
                    "assumptions.json",
                    "application/json",
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
            series = df[field].to_numpy(dtype=float)
            low, high = min(0.0, float(series.min())), max(0.0, float(series.max()))
            span = high-low or 1.0
            points = " ".join(f"{i*300/max(len(series)-1,1):.1f},{64-(v-low)/span*56:.1f}" for i,v in enumerate(series))
            color = "#7dd3fc" if tint == "hero" else "#dc4561" if tint == "red" else "#15966b" if tint == "green" else "#4675bd"
            spark = f'<svg viewBox="0 0 300 72" width="100%" height="72" role="img" aria-label="{label} monthly trend"><line x1="0" y1="{64-low*-56/span:.1f}" x2="300" y2="{64-low*-56/span:.1f}" stroke="{color}" opacity="0.2"/><polyline points="{points}" fill="none" stroke="{color}" stroke-width="2.5" stroke-linejoin="round"/></svg><div class="kpi-note">Monthly trend · M1 {_fmt_dollar_scaled(series[0])} → M{len(series)} {_fmt_dollar_scaled(series[-1])}</div>'
            cards.append(f'<div class="kpi {tint}"><div class="kpi-label">{label}</div><div class="kpi-years">{"".join(values)}</div>{spark}<div class="kpi-footer">{footer}</div></div>')
        st.markdown('<div class="kpi-grid">' + ''.join(cards) + '</div>', unsafe_allow_html=True)
        st.caption("Year 1 = forecast months 1–12; Year 2 = months 13–24. Balances are year-end snapshots; all other KPIs are annual totals.")


        render_forecast_charts(df, current, focus, product_risks, product_fits)

    if section == "Model assumptions":
        st.subheader("Model assumptions")
        st.table(pd.DataFrame([
            ("Opening CLAB", f"${sum(v['opening_gross_clab'] for v in all_inputs.values())/1e6:,.2f}M; allocation above", "Editable"),
            ("Credit source", mode + "; adjustments above", "Synthetic / manual"),
            ("Opening age", " / ".join(f"{k}: " + ("even by MOB" if v['opening_age_months'] is None else f"MOB {v['opening_age_months']}") for k,v in all_inputs.items()), "Assumed"),
            ("Revenue", "(Opening CLAB − charge-offs) × annual yield / 12", "New lending earns next month"),
            ("Provision", "Lifetime expected loss on new lending", "Opening reserve carried forward"),
            ("Loss severity", "100%; no recoveries", "Charge-offs reduce loans and reserve"),
            ("Repayment", "Scheduled amortization + full payoff", "No explicit redraws"),
            ("Presets", "Upside / Downside: ±1pp monthly growth; ±3pp approval vs Base", "Other inputs retained"),
        ], columns=["Assumption", "Current basis", "Treatment"]).set_index("Assumption"))
        st.caption("Reported totals are reference anchors. Product allocation, credit curves and yields are illustrative, not calibrated Propel assumptions.")

if section != "Vintage Analysis & Overlay":
    render_driver_panel_and_forecast()

if section == "Vintage Analysis & Overlay":
    highlight_scenario_controls()
    st.subheader("Applied curves vs synthetic history")
    if st.toggle("Show vintage curve comparison", value=False, key="show_vintage_comparison"):
        render_curve_comparison(product_risks, product_fits)
    st.caption("The forecast uses the source and adjustments selected above. Historical triangles below always show the original 2,000,000-loan synthetic dataset; edits do not rewrite history.")
    from vintage_analysis import render_vintage_analysis
    render_vintage_analysis()

from ai_chat import render_chat
if section == "Vintage Analysis & Overlay":
    st.session_state["ai_context"] = current_ai_context({k: args(k, historical) for k in PRODUCT_DEFAULTS})
render_chat()

if st.session_state.pop("compare_scenarios", False):
    show_scenario_comparison()
