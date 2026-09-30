import sys,json,copy
from pathlib import Path
root=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(root))
from curve_model import *
from payment_curves import load_payment_curves
from dashboard_support import PRODUCT_DEFAULTS
from product_forecast import segment_forecasts,combine
from excel_export import export_model

raw=load_payment_curves()
settings={mode:default_settings(mode,raw) for mode in SOURCES}
inputs={p:dict(monthly_applications_base=d['applications'],seasonality_pattern=[1.]*12,
              approval_rate_pct=d['approval_rate'],avg_loan_size=d['avg_loan_size'],
              annual_yield_pct=d['annual_yield'],term_months=d['term_months'],
              horizon_months=24,midpoint_months=1.,total_default_rate_pct=20.,
              opening_gross_clab=255600000. if p=='Short-Term' else 383400000.,
              opening_age_months=None,monthly_growth_pct=0.) for p,d in PRODUCT_DEFAULTS.items()}
snapshot=dict(source=SYNTHETIC,scenario='Base',view='Combined',creditfresh_share=.8,
              curve_settings=settings,historical_segment_risks=raw,segment_risks=raw,
              products={p:dict(active=a,manual_rate_pct=20.,manual_midpoint=1.,historical_rate_pct=20.,historical_midpoint=1.,stress_pct=0.) for p,a in inputs.items()})
work=Path(sys.argv[1]).resolve(); work.mkdir(parents=True,exist_ok=True)
(work/'forecast-check.xlsx').write_bytes(export_model(snapshot))
cases=[]
for name,source,pd_rate,dt,pt,mix,view in [
    ('synthetic_base',SYNTHETIC,None,1.,1.,.8,'Combined'),
    ('synthetic_adjusted',SYNTHETIC,35.,.5,2.,.8,'Combined'),
    ('manual_base',MANUAL,None,2.2,2.5,.8,'Combined'),
    ('manual_adjusted',MANUAL,30.,.75,.5,.65,'Short-Term'),
    ('zero_pd',SYNTHETIC,0.,1.,1.,1.,'Combined'),
    ('high_pd',SYNTHETIC,99.,4.,.25,0.,'Installment')]:
    config=copy.deepcopy(settings[source]); key='CreditFresh Short-Term'
    if pd_rate is not None: config[key]['pd']=pd_rate
    config[key].update(default_timing=dt,payoff_timing=pt)
    # Extreme case affects the segment included in the chosen view.
    if name=='high_pd':
        key='MoneyKey Installment'; config[key].update(pd=pd_rate,default_timing=dt,payoff_timing=pt)
    risks=build_curves(source,config,raw)
    forecasts=segment_forecasts(inputs,mix,risks)
    kinds=list(inputs) if view=='Combined' else [view]
    f=combine(book[k] for book in forecasts.values() for k in kinds)
    cases.append(dict(name=name,source=source,settings=config,mix=mix,view=view,
                      expected=f.to_dict(orient='list')))
(work/'excel-cases.json').write_text(json.dumps(cases))
