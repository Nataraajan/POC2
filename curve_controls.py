"""Shared controls for forecasting and the single vintage analysis workflow."""
import streamlit as st
import numpy as np
from segments import SEGMENTS
from curve_model import SYNTHETIC, MANUAL, SOURCES, default_settings, build_curves


def state_key(source, segment, field):
    return f"driver_curve_{source}_{segment}_{field}"


def render_controls(empirical, expanded=False):
    if st.session_state.get("driver_source") not in SOURCES:
        st.session_state["driver_source"] = SYNTHETIC
    st.selectbox("Curve source", SOURCES, key="driver_source")
    source = st.session_state["driver_source"]
    for mode in SOURCES:
        for segment, fields in default_settings(mode, empirical).items():
            for field, value in fields.items():
                st.session_state.setdefault(state_key(mode, segment, field), float(value))
                # Preserve the inactive source's controls across Streamlit reruns.
                k = state_key(mode, segment, field)
                st.session_state[k] = st.session_state[k]

    def restore():
        for segment, fields in default_settings(source, empirical).items():
            for field, value in fields.items():
                st.session_state[state_key(source, segment, field)] = float(value)

    with st.expander("Curve assumptions and adjustments", expanded=expanded):
        st.caption("Changes apply immediately to the forecast. Each source remembers its own settings.")
        if source == SYNTHETIC:
            st.caption("Original synthetic history stays unchanged. Timing 1 preserves the observed curve; below 1 moves events earlier, above 1 later.")
        else:
            st.caption("Manual curves are independent of synthetic history. Timing 1 spreads events evenly across the term; below 1 is earlier, above 1 later.")
        for segment in SEGMENTS:
            st.markdown(f"**{segment} · {SEGMENTS[segment]['term_months']} months**")
            cols = st.columns(3)
            cols[0].number_input("Lifetime default (%)", 0.0, 99.0, step=.5,
                                 key=state_key(source, segment, "pd"))
            cols[1].number_input("Default timing", .25, 4.0, step=.05,
                                 key=state_key(source, segment, "default_timing"))
            cols[2].number_input("Payoff timing", .25, 4.0, step=.05,
                                 key=state_key(source, segment, "payoff_timing"))
        st.button("Reset this source's curves", on_click=restore)
        st.caption("Payoff means full loan closure, alongside scheduled principal repayments. Default and payoff outcomes are mutually exclusive. LGD 100%, no recoveries. These are hypothetical POC assumptions, not calibrated Propel credit assumptions.")
    settings = {mode: {segment: {field: st.session_state[state_key(mode, segment, field)]
                    for field in ("pd", "default_timing", "payoff_timing")}
                    for segment in SEGMENTS} for mode in SOURCES}
    curves = {mode: build_curves(mode, settings[mode], empirical) for mode in SOURCES}
    return source, settings, curves


def render_curve_comparison(applied, empirical):
    import plotly.graph_objects as go
    segment = st.selectbox("Curve segment", list(SEGMENTS), key="curve_segment")
    term = SEGMENTS[segment]["term_months"]
    ages = np.arange(term + 1)
    fig = go.Figure()
    for label, risk, dash in [("Original synthetic", empirical[segment], "dot"),
                              ("Applied forecast", applied[segment], "solid")]:
        for event, color in [("default", "#DC2626"), ("payoff", "#2563EB")]:
            mass = risk["total_default_rate_pct"] if event == "default" else 100-risk["total_default_rate_pct"]
            fig.add_scatter(x=ages, y=np.asarray(risk[event+"_shape"])[:term+1]*mass,
                            name=f"{label} · {event}", line=dict(color=color, dash=dash))
    fig.update_layout(height=370, xaxis_title="Months on book", yaxis_title="Cumulative share (%)",
                      legend=dict(orientation="h", y=-.25), margin=dict(t=10, b=100))
    st.plotly_chart(fig, width="stretch")
    st.caption("Dotted curves are the unchanged synthetic observations. Solid curves are the exact inputs used by the forecast and Excel.")
