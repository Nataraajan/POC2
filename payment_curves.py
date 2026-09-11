"""Observed default/payoff timing from the same eligible mature vintages."""
import numpy as np
import pandas as pd
from pathlib import Path
from generate_loans import PRODUCTS


def derive_payment_curves(loans):
    result={}
    for brand,cfg in PRODUCTS.items():
        sub=loans[loans['product']==brand].copy()
        ages=pd.Period('2026-06','M').ordinal-sub.vintage.map(lambda x:pd.Period(x,'M').ordinal)
        # Same fully observable vintages at every age avoids changing denominators.
        sub=sub[ages>=cfg['term_months']]
        denom=sub.ticket.sum()
        d=np.array([sub.loc[(sub.default_mob>=0)&(sub.default_mob<=m),'ticket'].sum()/denom for m in range(37)])
        p=np.array([sub.loc[(sub.payoff_mob>=0)&(sub.payoff_mob<=m),'ticket'].sum()/denom for m in range(37)])
        result[brand]={'total_default_rate_pct':float(d[-1]*100),'midpoint_months':1.0,
                       'default_shape':(d/d[-1] if d[-1] else np.linspace(0,1,37)).tolist(),
                       'payoff_shape':(p/p[-1] if p[-1] else np.linspace(0,1,37)).tolist()}
    return result


def load_payment_curves():
    import json
    return json.loads((Path(__file__).parent/'data/payment_curves.json').read_text())
