"""Observed default/payoff timing from the same eligible mature vintages."""
import numpy as np
import pandas as pd
from pathlib import Path
from generate_loans import PRODUCTS
from build_triangle import OBSERVATION_DATE, TERMS


def derive_payment_curves(loans):
    if not set(loans['product']).issubset(PRODUCTS):
        raise ValueError('History must identify exact brand/loan-type segments')
    if not loans.term_months.eq(loans['product'].map(TERMS)).all():
        raise ValueError('History terms do not match segments')
    result={}
    for brand,cfg in PRODUCTS.items():
        sub=loans[loans['product']==brand].copy()
        ages=OBSERVATION_DATE.ordinal-sub.vintage.map(lambda x:pd.Period(x,'M').ordinal)
        # Same fully observable vintages at every age avoids changing denominators.
        sub=sub[ages>=cfg['term_months']]
        denom=sub.ticket.sum()
        if not np.isfinite(denom) or denom <= 0:
            raise ValueError(f'No positive-balance fully observed vintages for {brand}')
        d=np.array([sub.loc[(sub.default_mob>=0)&(sub.default_mob<=m),'ticket'].sum()/denom for m in range(37)])
        p=np.array([sub.loc[(sub.payoff_mob>=0)&(sub.payoff_mob<=m),'ticket'].sum()/denom for m in range(37)])
        # With no events, timing is unidentifiable: use a disclosed term-end
        # fallback, whose mass is zero unless the user changes manual PD.
        fallback=(np.arange(37)>=cfg['term_months']).astype(float)
        result[brand]={'term_months':cfg['term_months'],
                       'eligible_loans':len(sub), 'eligible_balance':float(denom),
                       'observation_month':str(OBSERVATION_DATE),
                       'default_timing_fallback':not bool(d[-1]),
                       'payoff_timing_fallback':not bool(p[-1]),
                       'total_default_rate_pct':float(d[-1]*100),'midpoint_months':1.0,
                       'default_shape':(d/d[-1] if d[-1] else fallback).tolist(),
                       'payoff_shape':(p/p[-1] if p[-1] else fallback).tolist()}
    return result


def load_payment_curves():
    import json
    return json.loads((Path(__file__).parent/'data/payment_curves.json').read_text())
