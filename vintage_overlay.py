"""Vintage assumption experiment and explicit forecast overlay handoff."""
import numpy as np
import pandas as pd
import plotly.graph_objects as go
import streamlit as st
from generate_loans import generate, PRODUCTS
from build_triangle import build_triangle, build_overlay_curve
from segments import SEGMENTS


def render_overlay(all_inputs, share=0.8, current_risks=None):
    st.subheader('Vintage overlay')
    st.caption('Segment default assumptions → generated loans → censored triangle → empirical default/payoff curves → matching segment forecast → day-one PLL. Hypothetical POC, not calibrated Propel assumptions.')
    with st.form('overlay_experiment'):
        cols = st.columns(4)
        rates = {p: cols[i].number_input(f'{p} lifetime default (%)', 0.0, 50.0, float(d['lifetime_default']*100), .5, format='%.1f') for i,(p,d) in enumerate(PRODUCTS.items())}
        run = st.form_submit_button('Generate vintage curves', type='primary')
    if run:
        with st.spinner('Generating 100,000 loans and building the censored curves…'):
            loans = generate(total_rows=100_000, verbose=False, lifetime_default_overrides={p:r/100 for p,r in rates.items()})
            triangle = build_triangle(loans)
            overlay = build_overlay_curve(triangle)
            st.session_state['overlay_experiment_result'] = {'triangle':triangle, 'overlay':overlay, 'fits':__import__('payment_curves').derive_payment_curves(loans), 'rates':rates}
    experiment = st.session_state.get('overlay_experiment_result')
    if experiment is None:
        st.info('Generate curves to preview their impact. This does not change the forecast until you apply a mapping below.')
        return
    st.caption('Last generated assumptions: ' + ' · '.join(f'{p} {r:.1f}%' for p,r in experiment['rates'].items()))
    st.write('Each curve maps directly to the same brand and loan type: Short-Term 12 months; Installment 24 months.')
    mapping={p:p for p in PRODUCTS}
    fig = go.Figure()
    for source, fit in experiment['fits'].items():
        rows = experiment['overlay'].query('product == @source')
        fig.add_scatter(x=rows.mob,y=rows.cum_default*100,name=source+' · derived',mode='lines+markers',hovertemplate='%{x} MOB · %{y:.2f}%<extra>%{fullData.name}</extra>')
        fig.add_scatter(x=rows.mob,y=np.interp(rows.mob,np.arange(37),fit['default_shape'])*fit['total_default_rate_pct'],name=source+' · applied to forecast',line=dict(dash='dot'),hovertemplate='%{x} MOB · %{y:.2f}%<extra>%{fullData.name}</extra>')
        fig.add_scatter(x=list(range(37)),y=np.array(fit['payoff_shape'])*(100-fit['total_default_rate_pct']),name=source+' · payoff applied',line=dict(dash='dash'))
    fig.update_layout(height=380,legend=dict(orientation='h',y=-.25),margin=dict(t=10,b=110),xaxis_title='Months on book',yaxis_title='Cumulative share (%)',paper_bgcolor='white',plot_bgcolor='white')
    st.plotly_chart(fig,width='stretch')
    st.caption('The plotted default curve and the curve applied to the forecast use the same fully observed vintages and denominator. Each segment has its own default and payoff timing at the same term. Excel receives these same empirical arrays; no sigmoid fit or term stretching is used.')
    ready = all(v != 'Choose source' for v in mapping.values())
    candidate = experiment['fits']
    from product_forecast import segment_forecasts, combine, default_product_curves
    before=segment_forecasts(all_inputs,share,current_risks or default_product_curves())
    after=segment_forecasts(all_inputs,share,candidate)
    impacts=[]
    for key, cfg in SEGMENTS.items():
        brand, loan_type = cfg['brand'], cfg['loan_type']
        old=before[brand][loan_type]; new=after[brand][loan_type]
        impacts.append({'Segment':key,'Empirical PD %':candidate[key]['total_default_rate_pct'],'Current PLL $':old.new_provisions.sum(),'Preview PLL $':new.new_provisions.sum(),'Revenue change $':new.revenue.sum()-old.revenue.sum()})
    st.dataframe(pd.DataFrame(impacts),hide_index=True,width='stretch')
    if st.button('Apply overlay to forecast',disabled=not ready,type='primary'):
        st.session_state['applied_overlay']={'product_fits':candidate,'mapping':mapping.copy(),'rates':experiment['rates'].copy()}
        st.session_state['driver_source']='Historical vintage'
        st.rerun()
    applied=st.session_state.get('applied_overlay')
    if applied:
        st.success('Applied mapping: '+' · '.join(f'{p} ← {s}' for p,s in applied['mapping'].items()))
        if st.button('Restore original historical curves'):
            del st.session_state['applied_overlay']
            st.rerun()
    with st.expander('Inspect generated vintage triangle'):
        source=st.selectbox('Triangle source',list(PRODUCTS))
        tri=experiment['triangle'].query('product == @source').pivot(index='vintage',columns='mob',values='observed_cum')
        st.dataframe(tri.style.format('{:.1%}',na_rep=''),width='stretch')
