"""Independent segment, censoring, mapping and accounting regression checks."""
import copy
import json
from pathlib import Path
import sys

import numpy as np
import pandas as pd
import pytest

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
from segments import SEGMENTS, segment_key
from generate_loans import generate
from build_triangle import build_triangle, build_overlay_curve, months_elapsed
from payment_curves import derive_payment_curves, load_payment_curves
from product_forecast import segment_forecasts, combine


@pytest.fixture(scope='module')
def loans():
    return generate(100_003,verbose=False)


def inputs():
    return {p:dict(monthly_applications_base=1000,seasonality_pattern=[1.]*12,
                   approval_rate_pct=40.,avg_loan_size=1500.,annual_yield_pct=50.,
                   midpoint_months=2.,total_default_rate_pct=20.,term_months=term,
                   horizon_months=36,opening_gross_clab=1e6,opening_age_months=None,
                   monthly_growth_pct=0.) for p,term in [('Line of Credit',12),('Installment',24)]}


def test_exact_segments_outcomes_and_reproducibility(loans):
    assert len(loans)==100_003 and loans.loan_id.is_unique
    assert set(loans['product'])==set(SEGMENTS)
    pd.testing.assert_frame_equal(loans,generate(100_003,verbose=False))
    for key,cfg in SEGMENTS.items():
        sub=loans[loans['product']==key]
        assert set(sub.brand)=={cfg['brand']} and set(sub.loan_type)=={cfg['loan_type']}
        assert set(sub.term_months)=={cfg['term_months']}
        assert abs(len(sub)/len(loans)-cfg['share'])<.001
        assert ((sub.default_mob==-1) ^ (sub.payoff_mob==-1)).all()
        for col in ['default_mob','payoff_mob']:
            assert ((sub[col]==-1)|sub[col].between(1,cfg['term_months'])).all()
        assert abs(sub.default_flag.mean()-cfg['lifetime_default'])<.025


@pytest.mark.parametrize('n',[1,17,144])
def test_small_runs_preserve_exact_row_count(n):
    assert len(generate(n,verbose=False))==n


def test_censoring_and_independent_raw_dollar_reconstruction(loans):
    triangle=build_triangle(loans)
    overlay=build_overlay_curve(triangle)
    risks=derive_payment_curves(loans)
    for key,cfg in SEGMENTS.items():
        term=cfg['term_months']
        tri=triangle[triangle['product']==key]
        assert (tri.mob<=tri.vintage.map(months_elapsed)).all()
        assert tri.mob.max()==term
        mature=loans[(loans['product']==key)&(loans.vintage.map(months_elapsed)>=term)]
        d=np.array([mature.loc[mature.default_mob.between(1,m),'ticket'].sum()/mature.ticket.sum() for m in range(term+1)])
        p=np.array([mature.loc[mature.payoff_mob.between(1,m),'ticket'].sum()/mature.ticket.sum() for m in range(term+1)])
        risk=risks[key]
        np.testing.assert_allclose(overlay.loc[overlay['product']==key,'cum_default'],d,atol=1e-14)
        np.testing.assert_allclose(np.array(risk['default_shape'])[:term+1]*risk['total_default_rate_pct']/100,d,atol=1e-14)
        np.testing.assert_allclose(np.array(risk['payoff_shape'])[:term+1]*(1-risk['total_default_rate_pct']/100),p,atol=1e-14)
        for name in ['default_shape','payoff_shape']:
            shape=np.array(risk[name])
            assert shape[0]==0 and np.all(np.diff(shape)>=-1e-14)
            np.testing.assert_allclose(shape[term:],1)
        assert d[-1]+p[-1]==pytest.approx(1)


def test_future_outcomes_do_not_leak_into_curves(loans):
    changed=loans.copy()
    recent=changed.vintage.map(months_elapsed)<changed.term_months
    changed.loc[recent,'default_mob']=changed.loc[recent,'term_months']
    changed.loc[recent,'payoff_mob']=-1
    assert derive_payment_curves(changed)==derive_payment_curves(loans)
    pd.testing.assert_frame_equal(build_overlay_curve(build_triangle(changed)),build_overlay_curve(build_triangle(loans)))


@pytest.mark.parametrize('key',list(SEGMENTS))
def test_segment_risk_change_is_isolated_and_balances_reconcile(key):
    risks=load_payment_curves()
    before=segment_forecasts(inputs(),.8,risks)
    changed=copy.deepcopy(risks)
    changed[key]['total_default_rate_pct']+=10
    after=segment_forecasts(inputs(),.8,changed)
    for brand,frames in after.items():
        for kind,f in frames.items():
            if segment_key(brand,kind)==key:
                assert not np.allclose(f.new_provisions,before[brand][kind].new_provisions)
            else:
                pd.testing.assert_frame_equal(f,before[brand][kind])
            np.testing.assert_allclose(f.ending_gross_clab,f.beginning_gross_clab+f.originations-f.principal_repaid-f.charge_offs,atol=1e-8)
            np.testing.assert_allclose(f.ending_reserve,f.beginning_reserve+f.new_provisions-f.charge_offs,atol=1e-8)
    runoff=segment_forecasts({p:{**a,'monthly_applications_base':0} for p,a in inputs().items()},.8,changed)
    for frames in runoff.values():
        for f in frames.values():
            assert abs(f.ending_gross_clab.iloc[-1])<1e-7
            assert abs(f.ending_reserve.iloc[-1])<1e-7
            np.testing.assert_allclose(f.charge_offs.sum(),f.beginning_reserve.iloc[0])


def test_bad_term_and_missing_segment_fail_explicitly():
    args=inputs(); args['Line of Credit']['term_months']=9
    with pytest.raises(ValueError,match='source term'):
        segment_forecasts(args,.8,load_payment_curves())
    with pytest.raises(ValueError,match='exact'):
        generate(100,False,{'CreditFresh':.2})
    with pytest.raises(ValueError,match='Missing empirical'):
        segment_forecasts(inputs(),.8,{'CreditFresh':load_payment_curves()['CreditFresh Line of Credit']})


def test_no_mature_data_fails_and_zero_event_fallback(loans):
    with pytest.raises(ValueError,match='fully observed'):
        derive_payment_curves(loans[loans.vintage=='2026-06'])
    data=loans.copy()
    data.default_mob=-1; data.payoff_mob=data.term_months
    risks=derive_payment_curves(data)
    for key,r in risks.items():
        assert r['total_default_rate_pct']==0 and r['default_timing_fallback']
        assert r['default_shape'][r['term_months']]==1


def test_committed_outputs_are_consistent():
    risks=load_payment_curves()
    overlay=pd.read_csv(ROOT/'data/overlay_curve.csv')
    stats=json.loads((ROOT/'data/generation_stats.json').read_text())
    assert set(risks)==set(SEGMENTS)==set(overlay['product'])
    assert stats['generation']['total_rows']==stats['triangle']['rows_loaded']==2_000_000
    for key,cfg in SEGMENTS.items():
        r=risks[key]
        assert r['term_months']==cfg['term_months']
        np.testing.assert_allclose(overlay.loc[overlay['product']==key,'cum_default'],np.array(r['default_shape'])[:r['term_months']+1]*r['total_default_rate_pct']/100,atol=1e-14)


def test_excel_export_has_independent_segment_formulas_and_matching_caches():
    from io import BytesIO
    import zipfile
    import xml.etree.ElementTree as ET
    from excel_export import export_model, NS
    risks=load_payment_curves()
    snapshot={'source':'Historical vintage','scenario':'Base','view':'Combined',
              'creditfresh_share':.8,'segment_risks':risks,
              'products':{p:{'active':a,'manual_rate_pct':20.,'manual_midpoint':2.,
                             'historical_rate_pct':20.,'historical_midpoint':2.,'stress_pct':0.}
                          for p,a in inputs().items()}}
    output=export_model(snapshot)
    forecasts=segment_forecasts(inputs(),.8,risks)
    ns={'s':NS}
    with zipfile.ZipFile(BytesIO(output)) as book:
        assert all(b"Short-Term" not in book.read(name) for name in book.namelist() if name.endswith(".xml"))
        sheets={i:ET.fromstring(book.read(f'xl/worksheets/sheet{i}.xml')) for i in [1,2,5,6,7,8]}
        def cell(i,address):
            return sheets[i].find(f'.//s:c[@r="{address}"]',ns)
        def formula(i,address):
            return cell(i,address).find('s:f',ns).text
        def value(i,address):
            return float(cell(i,address).find('s:v',ns).text)
        for sheet,key,col,paycol in [(5,'CreditFresh Line of Credit','E','H'),(6,'CreditFresh Installment','J','M'),(7,'MoneyKey Line of Credit','F','I'),(8,'MoneyKey Installment','K','N')]:
            risk=risks[key]; cfg=SEGMENTS[key]
            assert formula(sheet,'E40')==f"'Assumptions'!{col}58"
            assert f"${col}$65:${col}$101" in formula(sheet,'D52')
            assert f"${paycol}$65:${paycol}$101" in formula(sheet,'J52')
            assert 'NA()' in formula(2,f'{col}58')  # reject mismatched terms in Excel too
            assert value(2,f'{col}54')==pytest.approx(risk['total_default_rate_pct']/100)
            for age in range(37):
                assert value(2,f'{col}{65+age}')==risk['default_shape'][age]
                assert value(2,f'{paycol}{65+age}')==risk['payoff_shape'][age]
            expected=forecasts[cfg['brand']][cfg['loan_type']]
            assert value(sheet,'G24')==pytest.approx(expected.revenue.iloc[0])
            assert value(sheet,'E24')==pytest.approx(expected.revenue.sum())
        expected=combine(f for frames in forecasts.values() for f in frames.values())
        assert value(1,'E24')==pytest.approx(expected.revenue.sum())


def test_segment_timing_is_distinct():
    curves=load_payment_curves()
    assert len({tuple(r['default_shape']) for r in curves.values()})==4
    assert len({tuple(r['payoff_shape']) for r in curves.values()})==4
