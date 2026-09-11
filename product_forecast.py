"""Product risk is applied before aggregation, independently for each loan type."""
from pathlib import Path
import pandas as pd
from clab_forecast_engine_v2 import forecast_clab_v2
from vintage_overlay import fit_overlay


def default_product_curves():
    return fit_overlay(pd.read_csv(Path(__file__).parent / 'data/overlay_curve.csv'))


def segment_forecasts(inputs, share, risks):
    result = {}
    for brand, weight in [('CreditFresh', share), ('MoneyKey', 1-share)]:
        result[brand] = {}
        for loan_type, base in inputs.items():
            a = dict(base, monthly_applications_base=base['monthly_applications_base']*weight,
                     opening_gross_clab=base['opening_gross_clab']*weight,
                     total_default_rate_pct=risks[brand]['total_default_rate_pct'],
                     midpoint_months=risks[brand]['midpoint_months'])
            result[brand][loan_type] = forecast_clab_v2(**a)
    return result


def combine(frames):
    frames=list(frames)
    result=sum(f.drop(columns='month') for f in frames)
    result.insert(0,'month',frames[0].month.to_numpy())
    return result
