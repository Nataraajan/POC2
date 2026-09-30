"""Product risk is applied before aggregation, independently for each loan type."""
from clab_forecast_engine_v2 import forecast_clab_v2
from segments import segment_key, LOAN_TERMS


def default_product_curves():
    from payment_curves import load_payment_curves
    return load_payment_curves()


def segment_forecasts(inputs, share, risks):
    result = {}
    for brand, weight in [('CreditFresh', share), ('MoneyKey', 1-share)]:
        result[brand] = {}
        for loan_type, base in inputs.items():
            key = segment_key(brand, loan_type)
            if key not in risks:
                raise ValueError(f'Missing empirical curves for segment {key}')
            risk = risks[key]
            if risk.get('term_months') != base['term_months'] or base['term_months'] != LOAN_TERMS[loan_type]:
                raise ValueError(f"{key}: forecast term must equal the {risk.get('term_months')}-month source term")
            a = dict(base, monthly_applications_base=base['monthly_applications_base']*weight,
                     opening_gross_clab=base['opening_gross_clab']*weight,
                     total_default_rate_pct=risk['total_default_rate_pct'],
                     midpoint_months=risk['midpoint_months'])
            a.update(default_shape=risk['default_shape'],payoff_shape=risk['payoff_shape'])
            result[brand][loan_type] = forecast_clab_v2(**a)
    return result


def combine(frames):
    frames=list(frames)
    result=sum(f.drop(columns='month') for f in frames)
    result.insert(0,'month',frames[0].month.to_numpy())
    return result
