"""Vintage assumption experiment and explicit forecast overlay handoff."""
import numpy as np
import pandas as pd
import plotly.graph_objects as go
import streamlit as st
from generate_loans import generate, PRODUCTS
from build_triangle import build_triangle, build_overlay_curve
from derive_vintage_curves import fit_default_curve
from clab_forecast_engine_v2 import cumulative_default_pct, forecast_clab_v2


def fit_overlay(overlay):
    result = {}
    for product, rows in overlay.groupby('product'):
        pooled = pd.DataFrame({'months_on_book': rows.mob, 'cumulative_default_pct': rows.cum_default*100, 'eligible_balance': 1.0})
        fit = fit_default_curve(pooled)
        fit['total_default_rate_pct'] = min(99.0, max(0.0, fit['total_default_rate_pct']))
        result[product] = fit
    return result


def render_overlay(all_inputs):
    st.subheader('Vintage overlay')
    st.caption('Default-rate assumption → generated loans → censored triangle → derived curve → fitted forecast curve → day-one PLL. Synthetic experiment based on your updated vintage app.')
    with st.form('overlay_experiment'):
        cols = st.columns(2)
        rates = {p: cols[i].number_input(f'{p} lifetime default (%)', 0.0, 50.0, float(d['lifetime_default']*100), .5, format='%.1f') for i,(p,d) in enumerate(PRODUCTS.items())}
        run = st.form_submit_button('Generate vintage curves', type='primary')
    if run:
        with st.spinner('Generating 100,000 loans and building the censored curves…'):
            loans = generate(total_rows=100_000, verbose=False, lifetime_default_overrides={p:r/100 for p,r in rates.items()})
            triangle = build_triangle(loans)
            overlay = build_overlay_curve(triangle)
            st.session_state['overlay_experiment_result'] = {'triangle':triangle, 'overlay':overlay, 'fits':fit_overlay(overlay), 'rates':rates}
    experiment = st.session_state.get('overlay_experiment_result')
    if experiment is None:
        st.info('Generate curves to preview their impact. This does not change the forecast until you apply a mapping below.')
        return
    st.caption('Last generated assumptions: ' + ' · '.join(f'{p} {r:.1f}%' for p,r in experiment['rates'].items()))
    st.write('Map these illustrative source curves to forecast products. This is a scenario mapping, not a claim that the brands correspond to these loan types.')
    mapping = {p: st.selectbox(f'Source curve for {p}', ['Choose source']+list(PRODUCTS), key='overlay_map_'+p) for p in all_inputs}
    fig = go.Figure()
    for source, fit in experiment['fits'].items():
        rows = experiment['overlay'].query('product == @source')
        fig.add_scatter(x=rows.mob,y=rows.cum_default*100,name=source+' · derived',mode='lines+markers',hovertemplate='%{x} MOB · %{y:.2f}%<extra>%{fullData.name}</extra>')
        fig.add_scatter(x=rows.mob,y=cumulative_default_pct(rows.mob,fit['midpoint_months'],fit['total_default_rate_pct']),name=source+' · fitted for forecast',line=dict(dash='dot'),hovertemplate='%{x} MOB · %{y:.2f}%<extra>%{fullData.name}</extra>')
    fig.update_layout(height=380,legend=dict(orientation='h',y=-.25),margin=dict(t=10,b=110),xaxis_title='Months on book',yaxis_title='Cumulative default (%)',paper_bgcolor='white',plot_bgcolor='white')
    st.plotly_chart(fig,width='stretch')
    st.caption('The forecast uses the dotted fitted approximation (fixed curve shape), not the raw points. Fit uses equal MOB weights; product stress is applied afterward. Excel receives the same fitted parameters. Different source and forecast terms can change realized lifetime losses.')
    ready = all(v != 'Choose source' for v in mapping.values())
    candidate = {}
    if ready:
        impacts=[]
        for product, source in mapping.items():
            fit=experiment['fits'][source]
            candidate[product]=fit
            base=dict(all_inputs[product])
            after=dict(base, midpoint_months=fit['midpoint_months'],total_default_rate_pct=fit['total_default_rate_pct']*(1+st.session_state[f'driver_{product}_stress']/100))
            before_df=forecast_clab_v2(**base); after_df=forecast_clab_v2(**after)
            impacts.append({'Forecast product':product,'Source':source,'Fitted PD %':fit['total_default_rate_pct'],'Midpoint MOB':fit['midpoint_months'],'Current PLL $':before_df.new_provisions.sum(),'Preview PLL $':after_df.new_provisions.sum(),'Revenue change $':after_df.revenue.sum()-before_df.revenue.sum()})
        st.dataframe(pd.DataFrame(impacts),hide_index=True,width='stretch')
    if st.button('Apply overlay to forecast',disabled=not ready,type='primary'):
        st.session_state['applied_overlay']={'fits':candidate,'mapping':mapping.copy(),'rates':experiment['rates'].copy()}
        st.session_state['driver_source']='Historical vintage'
        st.rerun()
    applied=st.session_state.get('applied_overlay')
    if applied:
        st.success('Applied mapping: '+' · '.join(f'{p} ← {s}' for p,s in applied['mapping'].items()))
        if st.button('Restore original historical fits'):
            del st.session_state['applied_overlay']
            st.rerun()
    with st.expander('Inspect generated vintage triangle'):
        source=st.selectbox('Triangle source',list(PRODUCTS))
        tri=experiment['triangle'].query('product == @source').pivot(index='vintage',columns='mob',values='observed_cum')
        st.dataframe(tri.style.format('{:.1%}',na_rep=''),width='stretch')
