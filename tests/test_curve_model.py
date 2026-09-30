import copy
import numpy as np
import pandas as pd
import pytest
from curve_model import build_curves, default_settings, SYNTHETIC, MANUAL
from payment_curves import load_payment_curves
from product_forecast import segment_forecasts
from test_segments import inputs
from segments import SEGMENTS


def test_identity_and_manual_independence():
    empirical = load_payment_curves()
    original = copy.deepcopy(empirical)
    curves = build_curves(SYNTHETIC, default_settings(SYNTHETIC, empirical), empirical)
    for key in SEGMENTS:
        for field in ('default_shape','payoff_shape','total_default_rate_pct'):
            np.testing.assert_allclose(curves[key][field],empirical[key][field],rtol=0,atol=0)
    settings=default_settings(MANUAL)
    a=build_curves(MANUAL,settings)
    b=build_curves(MANUAL,settings,{'unusable':'ignored'})
    assert a == b
    assert original == empirical


@pytest.mark.parametrize('mode',[SYNTHETIC,MANUAL])
@pytest.mark.parametrize('timing',[.25,1.,4.])
@pytest.mark.parametrize('pd_rate',[0.,99.])
def test_curve_bounds_and_portfolio_conservation(mode,timing,pd_rate):
    empirical=load_payment_curves()
    settings=default_settings(mode,empirical)
    for s in settings.values():
        s.update(pd=pd_rate,default_timing=timing,payoff_timing=4.25-timing)
    risks=build_curves(mode,settings,empirical)
    for key,r in risks.items():
        for event in ('default','payoff'):
            shape=np.array(r[event+'_shape'])
            assert shape[0]==0 and np.all(shape[r['term_months']:]==1)
            assert np.all(np.diff(shape)>=0)
        total=np.array(r['default_shape'])*pd_rate/100+np.array(r['payoff_shape'])*(1-pd_rate/100)
        assert np.max(total)<=1+1e-14
    args={p:{**a,'monthly_applications_base':0,'horizon_months':36} for p,a in inputs().items()}
    for book in segment_forecasts(args,.8,risks).values():
        for f in book.values():
            np.testing.assert_allclose(f.ending_gross_clab,f.beginning_gross_clab-f.charge_offs-f.principal_repaid,atol=1e-7)
            np.testing.assert_allclose(f.ending_reserve,f.beginning_reserve-f.charge_offs,atol=1e-7)
            assert f.ending_gross_clab.iloc[-1]==pytest.approx(0,abs=1e-6)
            assert f.ending_reserve.iloc[-1]==pytest.approx(0,abs=1e-6)
            assert f.principal_repaid.min()>=-1e-7


@pytest.mark.parametrize('field',['pd','default_timing','payoff_timing'])
def test_changes_are_segment_specific(field):
    raw=load_payment_curves()
    settings=default_settings(SYNTHETIC,raw)
    before=segment_forecasts(inputs(),.8,build_curves(SYNTHETIC,settings,raw))
    key='MoneyKey Installment'
    settings[key][field]=45. if field=='pd' else .5
    after=segment_forecasts(inputs(),.8,build_curves(SYNTHETIC,settings,raw))
    for name,cfg in SEGMENTS.items():
        old,new=before[cfg['brand']][cfg['loan_type']],after[cfg['brand']][cfg['loan_type']]
        if name==key:
            assert not np.allclose(old.revenue,new.revenue)
        else:
            pd.testing.assert_frame_equal(old,new)


@pytest.mark.parametrize('field,value',[('pd',-1),('pd',100),('pd',float('nan')),('default_timing',0),('payoff_timing',5)])
def test_invalid_controls_rejected(field,value):
    settings=default_settings(MANUAL)
    settings['CreditFresh Line of Credit'][field]=value
    with pytest.raises(ValueError):
        build_curves(MANUAL,settings)
