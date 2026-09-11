"""
CLAB Forecast POC — app.py

A lending-funnel forecasting proof of concept: applications -> approvals ->
originations -> gross CLAB (repayments + charge-offs) -> yield -> revenue,
with an expected-loss provision booked at origination (reserve, net CLAB,
net revenue). Default rates come from a vintage curve that can be either
assumed (tunable inputs) or fitted to historical loan-level data via real
SQL aggregation.

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
from clab_forecast_engine_v2 import forecast_clab_v2, aggregate_to_quarterly, cumulative_default_pct

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


DOLLAR_COLS = ["originations", "beginning_gross_clab", "principal_repaid", "charge_offs", "ending_gross_clab",
               "new_provisions", "beginning_reserve", "ending_reserve", "net_clab", "revenue", "net_revenue"]


def _display_table(df):
    out = df.copy()
    for col in DOLLAR_COLS:
        out[col] = out[col].apply(_fmt_dollar_scaled)
    out["applications"] = out["applications"].round(0)
    return out


def _flow_box(label, value, note="", color=NAVY):
    # "$" as an HTML entity: markdown would otherwise read a pair of dollar signs as a LaTeX formula.
    value, note = value.replace("$", "&#36;"), note.replace("$", "&#36;")
    return (f"<div style='border:1px solid #E2E8F0; border-top:3px solid {color}; border-radius:6px; "
            f"padding:6px 10px; min-width:118px; background:#FFFFFF;'>"
            f"<div style='font-size:0.72rem; color:#64748B;'>{label}</div>"
            f"<div style='font-size:1.05rem; font-weight:700; color:{color};'>{value}</div>"
            f"<div style='font-size:0.68rem; color:#94A3B8;'>{note}</div></div>")


def _flow_row(items):
    joined = "".join(item if item.startswith("<div") else
                     f"<div style='align-self:center; color:#94A3B8; font-size:1.1rem;'>{item}</div>" for item in items)
    return f"<div style='display:flex; flex-wrap:wrap; gap:6px; margin:4px 0;'>{joined}</div>"


def driver_flow(df, approved_loans, blended=False):
    """The revenue driver chain for the latest month, one box per step:
    Applications -> Approval Rate -> Originations -> Gross CLAB -> Yield -> Revenue,
    then Revenue - Provision Expense = Net Revenue as its own line."""
    last = df.iloc[-1]
    earning_balance = last["beginning_gross_clab"] - last["charge_offs"]
    approval = approved_loans / last["applications"] if last["applications"] else 0.0
    avg_size = last["originations"] / approved_loans if approved_loans else 0.0
    yield_annual = last["revenue"] * 12 / earning_balance if earning_balance else 0.0
    tag = "blended" if blended else ""
    st.markdown(f"<div style='font-size:0.8rem; font-weight:600; color:{NAVY}; margin-top:6px;'>"
                f"Revenue driver flow — month {int(last['month'])}</div>", unsafe_allow_html=True)
    st.markdown(_flow_row([
        _flow_box("Applications", f"{last['applications']:,.0f}", "this month"),
        "→", _flow_box("× Approval rate", f"{approval:.1%}", f"{approved_loans:,.0f} loans {tag}".strip()),
        "→", _flow_box("Originations", _fmt_dollar_scaled(last["originations"]), f"× {_fmt_dollar_scaled(avg_size)} avg loan {tag}".strip()),
        "→", _flow_box("Gross CLAB", _fmt_dollar_scaled(last["ending_gross_clab"]), f"{_fmt_dollar_scaled(earning_balance)} earning interest"),
        "→", _flow_box("× Yield", f"{yield_annual:.1%} / yr", f"÷ 12 per month {tag}".strip()),
        "→", _flow_box("Revenue", _fmt_dollar_scaled(last["revenue"]), "interest earned", GREEN),
    ]) + _flow_row([
        _flow_box("Revenue", _fmt_dollar_scaled(last["revenue"]), "", GREEN),
        "−", _flow_box("Provision expense", _fmt_dollar_scaled(last["new_provisions"]), "booked at origination", RED),
        "=", _flow_box("Net revenue", _fmt_dollar_scaled(last["net_revenue"]), "revenue after expected losses", NAVY),
    ]), unsafe_allow_html=True)
    st.caption("Revenue is yield on the balance earning interest this month — opening gross CLAB less this month's "
               "charge-offs. This month's originations start earning next month, while their full lifetime "
               "provision hits the P&L now.")


def gross_reserve_net_display(gross, reserve):
    """Gross, Reserve and Net formatted in one shared unit (the gross figure's), with the
    displayed Net taken from the displayed Gross and Reserve — so the three always foot
    on screen, instead of rounding independently and appearing to be off by $0.01M."""
    divisor, suffix = (1_000_000, "M") if abs(gross) >= 1_000_000 else (1_000, "K") if abs(gross) >= 1_000 else (1, "")
    decimals = 2 if divisor > 1 else 0
    gross_shown, reserve_shown = round(gross / divisor, decimals), round(reserve / divisor, decimals)

    def fmt(v):
        return f"{'−' if v < 0 else ''}${abs(v):,.{decimals}f}{suffix}"
    return fmt(gross_shown), fmt(reserve_shown), fmt(round(gross_shown - reserve_shown, decimals))


def hero_metrics(df):
    last = df.iloc[-1]
    gross_text, reserve_text, net_text = gross_reserve_net_display(last["ending_gross_clab"], last["ending_reserve"])
    b1, b2, b3, b4 = st.columns(4)
    b1.metric("Ending Gross CLAB", gross_text,
              help="Total loan balance outstanding, before any loss reserve.")
    b2.metric("Ending Reserve", reserve_text,
              help="Loss allowance: provisions booked at origination, less charge-offs drawn against it.")
    b3.metric("Ending Net CLAB (Gross − Reserve)", net_text,
              help="Gross CLAB less the reserve — the book's carrying value after expected losses.")
    coverage = last["ending_reserve"] / last["ending_gross_clab"] if last["ending_gross_clab"] else 0.0
    b4.metric("Reserve coverage (Reserve ÷ Gross)", f"{coverage:.1%}")
    p1, p2, p3, p4 = st.columns(4)
    p1.metric("Latest month revenue", _fmt_dollar_scaled(last["revenue"]))
    p2.metric("Latest month charge-offs", _fmt_dollar_scaled(last["charge_offs"]),
              help="Drawn from the reserve — not a second P&L expense.")
    p3.metric("Total revenue (horizon)", _fmt_dollar_scaled(df["revenue"].sum()))
    p4.metric("Total net revenue (horizon)", _fmt_dollar_scaled(df["net_revenue"].sum()),
              help="Revenue less provision expense, summed over the horizon.")


# Forecast charts are built as one-shot plain dicts rather than go.Figure + add_trace +
# update_layout: st.plotly_chart validates the figure either way, but skipping plotly's
# incremental object updates and underscore-path parsing makes each chart ~3x cheaper,
# and these redraw on every slider move.
def _line(df, col, name, color, width=3, dash="solid", fill=None):
    trace = {"type": "scatter", "mode": "lines", "x": df["month"].to_numpy(), "y": df[col].to_numpy(),
             "name": name, "line": {"color": color, "width": width, "dash": dash}}
    if fill:
        trace["fill"] = fill
    return trace


def _chart_layout(y_title, height=330, shapes=()):
    return {"xaxis": {"title": {"text": "Month"}}, "yaxis": {"title": {"text": y_title}}, "height": height,
            "hovermode": "x unified", "margin": {"l": 10, "r": 10, "t": 10, "b": 10},
            "legend": {"orientation": "h", "y": 1.14}, "shapes": list(shapes)}


def balance_and_pnl_charts(df, gross_color):
    left, right = st.columns(2)
    with left:
        st.markdown("**Loan book — Gross vs Net CLAB**")
        st.plotly_chart({"data": [
            _line(df, "ending_gross_clab", "Gross CLAB", gross_color, fill="tozeroy"),
            _line(df, "net_clab", "Net CLAB (Gross − Reserve)", NAVY),
            _line(df, "ending_reserve", "Reserve", AMBER, width=2, dash="dot"),
        ], "layout": _chart_layout("$")}, width="stretch")
    with right:
        st.markdown("**P&L — Revenue, Provision Expense, Net Revenue**")
        zero_line = {"type": "line", "xref": "paper", "x0": 0, "x1": 1, "y0": 0, "y1": 0,
                     "line": {"color": "#CBD5E1", "width": 1}}
        st.plotly_chart({"data": [
            _line(df, "revenue", "Revenue", GREEN),
            _line(df, "new_provisions", "Provision expense", RED),
            _line(df, "net_revenue", "Net revenue", NAVY, dash="dash"),
        ], "layout": _chart_layout("$ per month", shapes=[zero_line])}, width="stretch")
    st.caption("The full lifetime provision for each month's originations hits the P&L the month they're booked, "
               "while revenue builds only as the book earns interest — so net revenue starts negative and turns "
               "positive as the book seasons. Charge-offs draw down the reserve rather than hitting the P&L again.")


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
MONTH_LABELS = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"]


def product_inputs(product, render, use_derived_curve, fitted_curves):
    """One product's assumptions. Values live in session state under the widget keys, so a
    product's inputs keep driving the forecast (and Combined) while its view is hidden.
    Widgets are drawn only when `render` is set, and without a `value=` argument — their
    starting value comes from the session-state default set here instead."""
    d = PRODUCT_DEFAULTS[product]
    ss = st.session_state
    for suffix, default in [("apps", d["applications"]), ("appr", d["approval_rate"]),
                            ("size", int(d["avg_loan_size"])), ("yield", d["annual_yield"]),
                            ("term", d["term_months"]), ("dtd", d["days_to_default"]),
                            ("tdr", d["total_default_rate"])] + [(f"season_{m}", 1.0) for m in range(12)]:
        ss.setdefault(f"{product}_{suffix}", default)

    if render:
        c1, c2, c3, c4, c5 = st.columns(5)
        c1.number_input("Applications/month", 100, 500_000, step=500, key=f"{product}_apps",
                        help="Baseline monthly application volume, before seasonality.")
        c2.slider("Approval rate (%)", 1.0, 100.0, key=f"{product}_appr")
        c3.number_input("Avg loan size ($)", 100, 100_000, step=100, key=f"{product}_size")
        c4.slider("Annual yield (%)", 0.0, 200.0, key=f"{product}_yield",
                  help="Annualized yield on the loan book. Also the contractual rate behind the repayment "
                       "schedule — the interest borrowers pay is the revenue.")
        c5.number_input("Loan term (months)", 1, 60, key=f"{product}_term",
                        help="Loans repay on a level-payment schedule over this term, shrinking CLAB as they do.")
        with st.expander("Seasonality (12-month pattern)"):
            st.caption("Explicit, user-set monthly multipliers — cycles automatically for horizons beyond 12 months.")
            season_cols = st.columns(6)
            for m in range(12):
                season_cols[m % 6].slider(MONTH_LABELS[m], 0.5, 1.5, key=f"{product}_season_{m}")

    if use_derived_curve:
        fit = fitted_curves[product]
        total_default_rate, midpoint_months = fit["total_default_rate_pct"], fit["midpoint_months"]
        if render:
            st.info(f"Using default curve fitted to historical data: {total_default_rate:.2f}% total default rate, "
                    f"~{fit['days_to_default']:.0f} days to default (see 'Vintage Analysis' below).", icon="📊")
    else:
        if render:
            d1, d2 = st.columns(2)
            d1.number_input("Days to default", 1, 365, key=f"{product}_dtd")
            d2.slider("Total default rate (%)", 0.0, 50.0, key=f"{product}_tdr")
        total_default_rate, midpoint_months = ss[f"{product}_tdr"], ss[f"{product}_dtd"] / 30.0

    term_months = ss[f"{product}_term"]
    if render:
        share_of_curve_within_term = cumulative_default_pct(term_months, midpoint_months, 1.0)
        if share_of_curve_within_term < 0.95:
            st.warning(f"Only {share_of_curve_within_term:.0%} of the default curve falls within the {term_months}-month term. "
                       f"Loans that have already repaid can't default, so realized losses will run below the "
                       f"{total_default_rate:.1f}% headline rate.")

    return dict(applications=ss[f"{product}_apps"], approval_rate=ss[f"{product}_appr"],
                avg_loan_size=ss[f"{product}_size"], annual_yield=ss[f"{product}_yield"], term_months=term_months,
                seasonality=[ss[f"{product}_season_{m}"] for m in range(12)],
                total_default_rate=total_default_rate, midpoint_months=midpoint_months)

# ===========================================================================
# FORECAST — a fragment: moving any forecast input reruns only this section,
# not the Vintage Analysis section below, which doesn't depend on those inputs.
# ===========================================================================
@st.fragment
def forecast_section():
    # --- ASSUMPTIONS ---
    st.subheader("Forecast Settings")
    s1, s2 = st.columns(2)
    horizon_months = s1.slider("Horizon (months)", 6, 36, 24)
    use_derived_curve = s2.checkbox("Overlay default curve fitted to historical data (vintage analysis)", value=False,
                                     help="Off: use the assumption inputs below directly. On: fit the default curve to mock historical loan-level data (SQL vintage triangle), and use that instead.")

    # One view at a time (not st.tabs): every tab's charts stay live in the browser, so with
    # tabs a single slider move redrew six Plotly charts. Every product is still forecast on
    # every run — Combined needs them all — but only the selected view is drawn.
    view = st.radio("View", list(PRODUCT_DEFAULTS.keys()) + ["Combined"], horizontal=True,
                    key="forecast_view", label_visibility="collapsed")

    # Keep hidden products' inputs alive: Streamlit discards a widget's value on any run where
    # it isn't drawn, so re-assert each stored value before drawing (the documented workaround).
    for key in [k for k in st.session_state if str(k).startswith(tuple(f"{p}_" for p in PRODUCT_DEFAULTS))]:
        st.session_state[key] = st.session_state[key]

    fitted_curves = None
    if use_derived_curve:
        try:
            _, _, fitted_curves = load_vintage_data()
        except FileNotFoundError:
            st.error("loans.csv not found — run `python generate_loan_data.py` first.")
            st.stop()

    product_forecasts = {}
    approved_loans_last_month = {}
    for product, defaults in PRODUCT_DEFAULTS.items():
        active = view == product
        if active:
            st.markdown(f"<h3 style='color:{defaults['color']};'>{product}</h3>", unsafe_allow_html=True)
        inputs = product_inputs(product, render=active, use_derived_curve=use_derived_curve, fitted_curves=fitted_curves)

        forecast_df = forecast_clab_v2(
            monthly_applications_base=inputs["applications"], seasonality_pattern=inputs["seasonality"],
            approval_rate_pct=inputs["approval_rate"], avg_loan_size=inputs["avg_loan_size"],
            annual_yield_pct=inputs["annual_yield"], midpoint_months=inputs["midpoint_months"],
            total_default_rate_pct=inputs["total_default_rate"], term_months=inputs["term_months"],
            horizon_months=horizon_months,
        )
        product_forecasts[product] = forecast_df
        approved_loans_last_month[product] = forecast_df["originations"].iloc[-1] / inputs["avg_loan_size"]

        if active:
            driver_flow(forecast_df, approved_loans_last_month[product])
            hero_metrics(forecast_df)
            balance_and_pnl_charts(forecast_df, defaults["color"])
            # A toggle rather than an expander: a collapsed expander still rebuilds its table on
            # every slider move (~100 ms in the browser); this builds it only while it's shown.
            if st.toggle("Show underlying monthly data", key=f"show_monthly_{product}"):
                st.dataframe(_display_table(forecast_df), width="stretch")

    # ===========================================================================
    # COMBINED VIEW
    # ===========================================================================
    if view == "Combined":
        st.markdown(f"<h3 style='color:{NAVY};'>Combined — All Products</h3>", unsafe_allow_html=True)
        combined_df = product_forecasts[list(PRODUCT_DEFAULTS.keys())[0]][["month"]].copy()
        for col in ["applications"] + DOLLAR_COLS:
            combined_df[col] = sum(product_forecasts[p][col] for p in PRODUCT_DEFAULTS.keys())

        driver_flow(combined_df, sum(approved_loans_last_month.values()), blended=True)
        hero_metrics(combined_df)
        balance_and_pnl_charts(combined_df, PURPLE)

        def floating_bridge(labels, bases, heights, texts, colors):
            # Floating bars (base + height) rather than a waterfall trace, so each step can have its own
            # color — a waterfall only allows one "decrease" color, and repayments aren't losses.
            return {"data": [{"type": "bar", "x": labels, "base": bases, "y": heights, "marker": {"color": colors},
                              "text": [_fmt_dollar_scaled(v) for v in texts], "textposition": "outside",
                              "hoverinfo": "skip"}],
                    "layout": {"yaxis": {"title": {"text": "$"}}, "height": 360, "showlegend": False,
                               "margin": {"l": 10, "r": 10, "t": 30, "b": 10}}}

        originated = combined_df["originations"].sum()
        repaid = combined_df["principal_repaid"].sum()
        charged_off = combined_df["charge_offs"].sum()
        provisioned = combined_df["new_provisions"].sum()
        beginning_gross, ending_gross = combined_df["beginning_gross_clab"].iloc[0], combined_df["ending_gross_clab"].iloc[-1]
        beginning_reserve, ending_reserve = combined_df["beginning_reserve"].iloc[0], combined_df["ending_reserve"].iloc[-1]

        bridge_left, bridge_right = st.columns(2)
        with bridge_left:
            st.markdown("#### Gross CLAB Bridge (full horizon)")
            st.plotly_chart(floating_bridge(
                ["Beginning Gross", "Originations", "Principal repaid", "Charge-offs", "Ending Gross"],
                [0, beginning_gross, beginning_gross + originated - repaid, ending_gross, 0],
                [beginning_gross, originated, repaid, charged_off, ending_gross],
                [beginning_gross, originated, -repaid, -charged_off, ending_gross],
                [NAVY, GREEN, AMBER, RED, NAVY]), width="stretch")
        with bridge_right:
            st.markdown("#### Reserve Bridge (full horizon)")
            st.plotly_chart(floating_bridge(
                ["Beginning Reserve", "New provisions", "Charge-offs", "Ending Reserve"],
                [0, beginning_reserve, ending_reserve, 0],
                [beginning_reserve, provisioned, charged_off, ending_reserve],
                [beginning_reserve, provisioned, -charged_off, ending_reserve],
                [NAVY, PURPLE, RED, NAVY]), width="stretch")
        gross_text, reserve_text, net_text = gross_reserve_net_display(ending_gross, ending_reserve)
        # Escape "$": markdown treats a pair of dollar signs as a LaTeX formula and swallows them.
        st.caption(f"Net CLAB = Ending Gross − Ending Reserve = {gross_text} − {reserve_text} = {net_text}. "
                   "The same charge-offs appear in both bridges: they shrink the gross book and use up reserve "
                   "already provisioned for them.".replace("$", r"\$"))

        st.markdown("#### Quarterly Rollup (matches how CLAB is reported externally)")
        quarterly_df = aggregate_to_quarterly(combined_df)
        st.dataframe(_display_table(quarterly_df)[["quarter", "applications", "originations", "beginning_gross_clab",
                                                    "principal_repaid", "charge_offs", "ending_gross_clab",
                                                    "new_provisions", "ending_reserve", "net_clab",
                                                    "revenue", "net_revenue"]],
                     width="stretch")
        trailing_months = horizon_months % 3
        if trailing_months:
            first_trailing = horizon_months - trailing_months + 1
            if trailing_months == 1:
                partial_note = f"Month {horizon_months} falls in a partial quarter and is left out of this table — it's"
            else:
                partial_note = f"Months {first_trailing}–{horizon_months} fall in a partial quarter and are left out of this table — they're"
            st.caption(f"{partial_note} still in the monthly data and the bridges above.")


forecast_section()

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
- **Provisions are booked at origination for each loan's full lifetime expected loss** (IFRS 9 lifetime / CECL-style — no 12-month Stage 1 bucket). They're sized on the amortizing balance, so they come in below the headline default rate, and each vintage's reserve runs down to zero as its charge-offs emerge.
- **Charge-offs are taken at the balance the defaulting loan still owed, with no recoveries** — so charge-offs are gross, not net of collections, and they draw down the reserve rather than hitting the P&L a second time.
- **The forecast starts from an empty book.** The historical loans are used to fit the default curve, not carried in as opening CLAB.
- **Originations = Applications × Approval Rate × Avg Loan Size directly** — no separate "approved but didn't take the loan" step modeled.
- **Annual yield is both the revenue yield and the contractual rate behind the repayment schedule** — fees aren't modeled separately.
- **Only the default curve's total rate and timing are fitted; its steepness is a fixed shape assumption**, shared by the assumption-based and fitted modes.
- **The historical data is synthetic**, with a known true curve baked in specifically so the derivation method could be validated against a ground truth — the same mechanism would run identically against real loan-level history.
""")
