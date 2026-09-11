"""
Vintage Analysis POC — vintage_app.py

A second standalone tool alongside the CLAB forecast (app.py). Presents a precomputed vintage analysis run (2,000,000 synthetic loans ->
SQL-aggregated, censored vintage triangle -> derived default curve) as the
explicit extraction -> computation -> output story, plus a live demo that
re-runs the same pipeline at small scale on demand.

Reads ONLY the small committed files in data/ — never loans.parquet. Every
headline number comes from data/generation_stats.json, written by an actual
run of generate_loans.py and build_triangle.py, not recomputed here.

Same visual language as the other tools (navy/green/blue/red palette) —
kept simple, not pixel-identical.
"""

import json
import time
from datetime import datetime
from pathlib import Path

import pandas as pd
import plotly.graph_objects as go
import streamlit as st

# The live demo calls these directly — no duplicated pipeline logic in this file.
from generate_loans import generate, PRODUCTS as GENERATOR_PRODUCTS
from build_triangle import build_triangle, build_overlay_curve, OBSERVATION_DATE, TERMS

DATA_DIR = Path(__file__).resolve().parent / "data"
LIVE_DEMO_ROWS = 100_000

NAVY = "#1E2761"
GREEN = "#16A34A"
BLUE = "#2563EB"
RED = "#DC2626"
PRODUCT_COLORS = {"CreditFresh": RED, "MoneyKey": BLUE}
PRODUCT_TINTS = {"CreditFresh": "#FEE2E2", "MoneyKey": "#DBEAFE"}  # light fills for observed triangle cells




def heading(text, level=2):
    st.markdown(f"<h{level} style='color:{NAVY}; margin-bottom:0.2rem;'>{text}</h{level}>", unsafe_allow_html=True)


@st.cache_data
def load_precomputed():
    """The four small committed output files. Deliberately nothing else."""
    stats = json.loads((DATA_DIR / "generation_stats.json").read_text())
    sample = pd.read_csv(DATA_DIR / "loans_sample.csv")
    triangle = pd.read_parquet(DATA_DIR / "vintage_triangle.parquet")
    overlay = pd.read_csv(DATA_DIR / "overlay_curve.csv")
    return stats, sample, triangle, overlay


def pct_text(frame):
    """Percent strings with truly empty cells for NaN — st.dataframe shows raw NaN as
    "None" even through a Styler's na_rep, which would read as broken data."""
    return frame.map(lambda v: "" if pd.isna(v) else f"{v:.1%}")


def triangle_table(triangle, product):
    """vintage x mob pivot of observed_cum. Cells a vintage hasn't reached yet are
    simply absent from the triangle, so they come out of the pivot as blanks."""
    pivot = (triangle[triangle["product"] == product]
             .pivot(index="vintage", columns="mob", values="observed_cum")
             .sort_index())
    pivot.columns = [f"MOB {mob}" for mob in pivot.columns]
    tint = PRODUCT_TINTS[product]
    styled = pct_text(pivot).style.map(lambda s: "" if s == "" else f"background-color: {tint}; color: #1A2233")
    return styled, len(pivot)


def show_triangle(triangle, product):
    styled, n_rows = triangle_table(triangle, product)
    st.dataframe(styled, width="stretch", height=35 * (n_rows + 1) + 3)


def curve_figure(overlay, reference=None, height=380, names=None):
    """names: optional {product: legend label} for the solid lines; defaults to the product name."""
    fig = go.Figure()
    if reference is not None:
        for product, color in PRODUCT_COLORS.items():
            ref = reference[reference["product"] == product]
            fig.add_trace(go.Scatter(x=ref["mob"], y=ref["cum_default"], name=f"{product} — 2M precomputed (reference)",
                                     mode="lines", line=dict(color=color, width=2, dash="dot"), opacity=0.45))
    for product, color in PRODUCT_COLORS.items():
        sub = overlay[overlay["product"] == product]
        fig.add_trace(go.Scatter(x=sub["mob"], y=sub["cum_default"], name=(names or {}).get(product, product),
                                 mode="lines+markers",
                                 line=dict(color=color, width=3),
                                 hovertemplate=f"{product} · MOB %{{x}}: %{{y:.1%}}<extra></extra>"))
    fig.update_layout(xaxis_title="Months on book (MOB)", yaxis_title="Cumulative default (% of originated $)",
                      yaxis_tickformat=".0%", xaxis_dtick=1, height=height,
                      margin=dict(l=10, r=10, t=10, b=10), legend=dict(orientation="h", y=1.12))
    return fig


def render_vintage_analysis():
    from payment_curves import load_payment_curves, derive_payment_curves
    st.subheader("36-vintage default and payoff analysis")
    st.caption("Updated 100,000-loan run: July 2023–June 2026. Both curves use fully mature vintages at the June 2026 cutoff. The older 2M run is retained below as a separate reference.")
    st.dataframe(pd.read_csv(DATA_DIR / "payment_sample.csv"),hide_index=True)
    payment_fig=go.Figure()
    for brand,risk in load_payment_curves().items():
        payment_fig.add_scatter(x=list(range(37)),y=[v*risk['total_default_rate_pct'] for v in risk['default_shape']],name=brand+' default')
        payment_fig.add_scatter(x=list(range(37)),y=[v*(100-risk['total_default_rate_pct']) for v in risk['payoff_shape']],name=brand+' payoff',line=dict(dash='dash'))
    payment_fig.update_layout(xaxis_title="Months on book",yaxis_title="Cumulative share (%)",height=320)
    st.plotly_chart(payment_fig,width="stretch")

    st.markdown(f"<h1 style='color:{NAVY};'>Vintage Analysis — Proof of Concept</h1>", unsafe_allow_html=True)
    st.caption("Loan-level data → SQL-aggregated vintage triangle, censored at the observation date → derived default curve.")

    try:
        stats, sample_df, triangle_df, overlay_df = load_precomputed()
    except FileNotFoundError as missing:
        st.error(f"Missing precomputed output: {missing.filename}. Run `python generate_loans.py` "
                 f"then `python build_triangle.py` first.")
        st.stop()

    gen_stats = stats["generation"]
    tri_stats = stats.get("triangle")
    if tri_stats is None:
        st.error("generation_stats.json has no triangle section — run `python build_triangle.py` after generate_loans.py.")
        st.stop()

    # ===========================================================================
    # HEADLINE STATS — facts about a real precomputed run, read from the stats file
    # ===========================================================================
    st.markdown(
        f"<p style='font-size:1.6rem; font-weight:700; color:{NAVY}; margin:0.6rem 0 0.2rem 0;'>"
        f"{gen_stats['total_rows']:,} loan records generated in {gen_stats['generation_seconds']:.1f}s, "
        f"aggregated via SQL in {tri_stats['triangle_build_seconds']:.1f}s</p>",
        unsafe_allow_html=True,
    )
    run_date = datetime.fromisoformat(tri_stats["run_at"]).strftime("%b %d, %Y at %H:%M")
    st.caption(
        f"Measured on a real precomputed run ({run_date}) of generate_loans.py → build_triangle.py, "
        f"read from data/generation_stats.json — nothing here is recomputed on page load. The SQL time includes "
        f"loading the rows into an in-memory SQLite database."
    )
    if tri_stats["rows_loaded"] != gen_stats["total_rows"]:
        st.warning(f"Stats mismatch: the triangle was built from {tri_stats['rows_loaded']:,} rows, but the latest "
                   f"generation run produced {gen_stats['total_rows']:,}. Re-run build_triangle.py.")

    h1, h2, h3, h4 = st.columns(4)
    h1.metric("Loan records", f"{gen_stats['total_rows']:,}")
    h2.metric(f"Vintages ({gen_stats['vintage_range'][0]} → {gen_stats['vintage_range'][1]})", gen_stats["vintages"])
    h3.metric("Triangle cells (observed)", f"{tri_stats['triangle_cells']:,}")
    h4.metric("Cells excluded by censoring", f"{tri_stats['cells_excluded_by_censoring']:,}")

    with st.expander("Validation checks from the same run", expanded=True):
        validation = pd.DataFrame([
            {
                "Product": product,
                "Mix — observed": f"{gen_stats['product_mix_pct'][product]['observed']:.1f}%",
                "Mix — target": f"{gen_stats['product_mix_pct'][product]['target']:.1f}%",
                "Lifetime default — observed": f"{gen_stats['default_rate_vs_target'][product]['observed']:.1%}",
                "Lifetime default — target": f"{gen_stats['default_rate_vs_target'][product]['target']:.1%}",
            }
            for product in PRODUCT_COLORS
        ])
        st.dataframe(validation, hide_index=True, width="stretch")
        st.caption(f"loan_id unique: {'yes' if gen_stats['loan_id_unique'] else 'NO'}. Each vintage's default rate "
                   "gets ±8% noise in the generator, so a small gap between observed and target is expected.")

    # ===========================================================================
    # METHODOLOGY — extraction -> computation -> output
    # ===========================================================================
    st.divider()
    heading("Methodology — extraction → computation → output")

    heading("1 · Extraction", level=4)
    st.caption(f"**Illustrative sample only** — {len(sample_df)} random rows from the generated file, not the analyzed "
               f"dataset. The full {gen_stats['total_rows']:,}-row file is never loaded by this app.")
    st.dataframe(sample_df, hide_index=True, width="stretch")
    st.caption("`default_mob` is each loan's true full-term outcome from the generator (−1 = never defaults) — the raw "
               "file effectively knows the future. Step 2 is where anything not yet observable gets thrown away.")

    heading("2 · Computation — SQL aggregation, then censoring", level=4)
    observation_label = OBSERVATION_DATE.to_timestamp(how="end").strftime("%B %d, %Y")
    st.markdown(
        f"The loan rows are loaded into an in-memory SQLite database and collapsed by two queries: dollars defaulted "
        f"per **product × vintage × month-on-book**, and dollars originated per **product × vintage**. Two million rows "
        f"become a few hundred.\n\n"
        f"Censoring is applied as those aggregates are assembled into the triangle: **a vintage only contributes a data "
        f"point at a given month-on-book if it's actually old enough to have reached it** by the observation date "
        f"({observation_label}) — `max_observable_mob = min(term, months elapsed)`. The SQL itself counts every default "
        f"in the file, including ones the generator placed in the future; this rule discards those. Skip it and every "
        f"vintage looks fully mature, which makes the curve artificially clean. In this run it excluded "
        f"**{tri_stats['cells_excluded_by_censoring']} cells**."
    )
    st.caption("Defaults by month-on-book — the exact query text from the run")
    st.code(tri_stats["sql_queries"]["defaults_by_mob"], language="sql")
    st.caption("Originations by vintage — the denominator")
    st.code(tri_stats["sql_queries"]["originations_by_vintage"], language="sql")

    heading("3 · Output — the derived curve", level=4)
    st.markdown(
        "For each month-on-book, pool the defaulted dollars across **only** the vintages that have reached it, divide by "
        "those vintages' originations, then accumulate. The result is `overlay_curve.csv` — a small derived output. The integrated Vintage overlay page fits and explicitly maps these curves into forecast parameters. Plotted in the curve chart below."
    )
    curve_table = overlay_df.pivot(index="mob", columns="product", values="cum_default")[list(PRODUCT_COLORS)]
    curve_table.index = [f"MOB {mob}" for mob in curve_table.index]
    st.dataframe(pct_text(curve_table), width="content")
    st.caption("Blank = beyond that product's term (" +
               ", ".join(f"{product} loans run {TERMS[product]} months" for product in PRODUCT_COLORS) + ").")

    # ===========================================================================
    # VINTAGE TRIANGLE VIEW
    # ===========================================================================
    st.divider()
    heading("Vintage triangle — cumulative default by vintage × month-on-book")
    triangle_product = st.radio("Product", list(PRODUCT_COLORS), horizontal=True, key="triangle_product")
    show_triangle(triangle_df, triangle_product)
    st.caption("Blank cells are the honest signature of censored data — those vintages haven't been on the books long "
               "enough to reach that month yet — not missing or broken data.")

    # ===========================================================================
    # CURVE CHART
    # ===========================================================================
    st.divider()
    heading("Derived default curve")
    st.plotly_chart(curve_figure(overlay_df), width="stretch")

    # ===========================================================================
    # LIVE DEMO — same functions, smaller scale, run on click
    # ===========================================================================
    st.divider()
    heading("Live demo")
    st.markdown(
        f"Pick a product, set its lifetime default rate, and run the same `generate()` and `build_triangle()` functions "
        f"from the scripts above on {LIVE_DEMO_ROWS:,} fresh rows, right now. The other product stays at its baseline, so "
        f"cause and effect is easy to follow. **Smaller scale and separate from the {gen_stats['total_rows']:,}-row "
        f"precomputed results above.**"
    )


    def fmt_rate(pct):
        return f"{pct:g}%"


    pick_col, rate_col = st.columns([1, 2])
    live_product = pick_col.radio("Product to tune", list(PRODUCT_COLORS), horizontal=True, key="live_product")
    baseline_pct = GENERATOR_PRODUCTS[live_product]["lifetime_default"] * 100
    # One slider key per product, so each starts at (and remembers) its own product's setting.
    live_rate_pct = rate_col.number_input(f"{live_product} lifetime default rate (%)", 0.0, 50.0, value=baseline_pct, step=0.5,
                                    key=f"live_rate_{live_product}",
                                    help=f"{live_product}'s baseline in the generator is {fmt_rate(baseline_pct)}.")

    if st.button("Run live demo", type="primary"):
        overrides = {live_product: live_rate_pct / 100}
        with st.spinner(f"Generating {LIVE_DEMO_ROWS:,} loans with {live_product} at {fmt_rate(live_rate_pct)} "
                        f"and building the triangle..."):
            t0 = time.perf_counter()
            live_loans = generate(total_rows=LIVE_DEMO_ROWS, verbose=False, lifetime_default_overrides=overrides)
            t1 = time.perf_counter()
            live_triangle = build_triangle(live_loans)
            live_overlay = build_overlay_curve(live_triangle)
            t2 = time.perf_counter()
        st.session_state["live_demo_run"] = {
            "payment_curves": derive_payment_curves(live_loans), "rows": len(live_loans), "generate_s": t1 - t0, "aggregate_s": t2 - t1, "total_s": t2 - t0,
            "triangle": live_triangle, "overlay": live_overlay, "ran_at": datetime.now().strftime("%H:%M:%S"),
            # The rates this run actually used, kept with the result — the label must not follow
            # the slider if it moves after the run.
            "tuned_product": live_product,
            "rates_pct": {p: (live_rate_pct if p == live_product else cfg["lifetime_default"] * 100)
                          for p, cfg in GENERATOR_PRODUCTS.items()},
        }

    live = st.session_state.get("live_demo_run")
    if live:
        tuned, rates = live["tuned_product"], live["rates_pct"]
        labels = {p: (f"{p} — tuned to {fmt_rate(rates[p])} lifetime default" if p == tuned
                      else f"{p} — baseline {fmt_rate(rates[p])}") for p in PRODUCT_COLORS}
        curve_ends = live["overlay"].groupby("product")["cum_default"].last()

        with st.container(border=True):
            st.markdown(f"<p style='color:{GREEN}; font-weight:700; margin:0;'>LIVE DEMO — {labels[tuned]} · smaller "
                        f"scale ({live['rows']:,} rows), run at {live['ran_at']}</p>", unsafe_allow_html=True)
            if (live_product, live_rate_pct) != (tuned, rates[tuned]):
                st.caption(f"Showing the last run ({labels[tuned]}). Click **Run live demo** to apply "
                           f"{live_product} at {fmt_rate(live_rate_pct)}.")
            l1, l2, l3, l4 = st.columns(4)
            l1.metric("Rows generated", f"{live['rows']:,}")
            l2.metric("Generate", f"{live['generate_s']:.2f}s")
            l3.metric("SQL aggregation + censoring", f"{live['aggregate_s']:.2f}s")
            l4.metric("Total elapsed", f"{live['total_s']:.2f}s")

            live_tabs = st.tabs(["Curve"] + [f"{product} triangle" for product in PRODUCT_COLORS])
            with live_tabs[0]:
                st.markdown(f"**{labels[tuned]}** — derived curve ends at {curve_ends[tuned]:.1%} "
                            f"(target {fmt_rate(rates[tuned])}). "
                            + " · ".join(f"{labels[p]}, derived {curve_ends[p]:.1%}" for p in PRODUCT_COLORS if p != tuned))
                st.plotly_chart(curve_figure(live["overlay"], reference=overlay_df, height=340, names=labels),
                                width="stretch")
                st.caption(f"Solid lines: this live run. Dotted: the {gen_stats['total_rows']:,}-row precomputed curves at "
                           f"baseline rates, for reference — the tuned product's curve moves to the new rate, the other "
                           f"stays on its reference line (a sample {gen_stats['total_rows'] / live['rows']:.0f}x smaller, "
                           f"so a little more noise).")
            for tab, product in zip(live_tabs[1:], PRODUCT_COLORS):
                with tab:
                    show_triangle(live["triangle"], product)


if __name__ == "__main__":
    st.set_page_config(page_title="Vintage Analysis POC", layout="wide")
    render_vintage_analysis()
