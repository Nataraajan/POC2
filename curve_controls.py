"""Shared controls for forecasting and the single vintage analysis workflow."""
import streamlit as st
import numpy as np
from segments import SEGMENTS
from curve_model import SYNTHETIC, MANUAL, SOURCES, default_settings, build_curves


def state_key(source, segment, field):
    return f"driver_curve_{source}_{segment}_{field}"


def render_controls(empirical, expanded=False, on_change=None):
    legacy = [state_key(SYNTHETIC, segment, field) for segment in SEGMENTS
              for field in ("default_timing", "payoff_timing")]
    if any(key in st.session_state for key in legacy):
        for key in legacy:
            st.session_state.pop(key, None)
        st.info("Synthetic timing multipliers have been replaced by month shifts, starting at 0. Your default-rate assumptions are retained.")
    if st.session_state.get("driver_source") not in SOURCES:
        st.session_state["driver_source"] = SYNTHETIC
    st.selectbox("Curve source", SOURCES, key="driver_source", on_change=on_change)
    source = st.session_state["driver_source"]
    for mode in SOURCES:
        for segment, fields in default_settings(mode, empirical).items():
            for field, value in fields.items():
                st.session_state.setdefault(state_key(mode, segment, field), int(value) if field.endswith("_shift_months") else float(value))
                # Preserve the inactive source's controls across Streamlit reruns.
                k = state_key(mode, segment, field)
                st.session_state[k] = st.session_state[k]

    def restore():
        if on_change:
            on_change()
        for segment, fields in default_settings(source, empirical).items():
            for field, value in fields.items():
                st.session_state[state_key(source, segment, field)] = int(value) if field.endswith("_shift_months") else float(value)

    with st.expander("Default & payoff assumptions", expanded=expanded):
        st.caption("Full payoff closes the remaining balance; scheduled repayments are calculated separately. Non-default payoff share = 100% minus lifetime default. Only payoff timing is independently editable.")
        st.caption("Changes apply immediately to the forecast. Each source remembers its own settings.")
        if source == SYNTHETIC:
            st.caption("Synthetic history stays unchanged. Shift 0 preserves it; +1 delays events one month, −1 brings them forward one month. Events cannot precede month 1. Scheduled amortization stays unchanged.")
        else:
            st.caption("Manual curves are independent of synthetic history. Timing 1 spreads events evenly across the term; below 1 is earlier, above 1 later.")
        for segment in SEGMENTS:
            st.markdown(f"**{segment} · {SEGMENTS[segment]['term_months']} months**")
            cols = st.columns(3)
            cols[0].number_input("Lifetime default (%)", 0.0, 99.0, step=.5,
                                 key=state_key(source, segment, "pd"), on_change=on_change)
            if source == SYNTHETIC:
                for col, event, label in [(cols[1], "default", "Default timing shift (months)"),
                                          (cols[2], "payoff", "Full-payoff timing shift (months)")]:
                    col.number_input(label, -12, 12, step=1,
                                     key=state_key(source, segment, event + "_shift_months"), on_change=on_change,
                                     help="0 = unchanged; positive = later; negative = earlier. Whole months only. Events shifted past the original window are retained, up to month 36.")
            else:
                cols[1].number_input("Default curve shape", .25, 4.0, step=.05,
                                     key=state_key(source, segment, "default_timing"), on_change=on_change)
                cols[2].number_input("Full-payoff curve shape", .25, 4.0, step=.05,
                                     key=state_key(source, segment, "payoff_timing"), on_change=on_change,
                                     help="Manual curve exponent, not months. Below 1 = earlier; above 1 = later.")
        st.button("Reset this source's curves", on_click=restore)
        st.caption("Payoff means full loan closure, alongside scheduled principal repayments. Default and payoff outcomes are mutually exclusive. LGD 100%, no recoveries. These are hypothetical POC assumptions, not calibrated Propel credit assumptions.")
    settings = {mode: {segment: {field: st.session_state[state_key(mode, segment, field)]
                    for field in default_settings(mode, empirical)[segment]}
                    for segment in SEGMENTS} for mode in SOURCES}
    curves = {mode: build_curves(mode, settings[mode], empirical) for mode in SOURCES}
    return source, settings, curves


def render_curve_comparison(applied, empirical):
    import plotly.graph_objects as go
    segment = st.selectbox("Curve segment", list(SEGMENTS), key="curve_segment")
    term = SEGMENTS[segment]["term_months"]
    ages = np.arange(int(applied[segment].get("curve_window_months", term)) + 1)
    fig = go.Figure()
    for label, risk, dash in [("Original synthetic", empirical[segment], "dot"),
                              ("Applied forecast", applied[segment], "solid")]:
        for event, color in [("default", "#DC2626"), ("payoff", "#2563EB")]:
            mass = risk["total_default_rate_pct"] if event == "default" else 100-risk["total_default_rate_pct"]
            fig.add_scatter(x=ages, y=np.asarray(risk[event+"_shape"])[:len(ages)]*mass,
                            name=f"{label} · {event}", line=dict(color=color, dash=dash))
    fig.update_layout(height=370, xaxis_title="Months on book", yaxis_title="Cumulative share (%)",
                      legend=dict(orientation="h", y=-.25), margin=dict(t=10, b=100))
    st.plotly_chart(fig, width="stretch")
    st.caption("Dotted curves are the unchanged synthetic observations. Solid curves are the exact inputs used by the forecast and Excel.")
