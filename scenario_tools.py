"""Read-only scenario previews using the same forecast engine as the dashboard."""
from copy import deepcopy
import math

from curve_model import build_curves, SYNTHETIC
from dashboard_support import PRODUCT_DEFAULTS
from product_forecast import segment_forecasts, combine
from propel_reference import MONTHLY_GROWTH_PCT


def preset_values(name, product):
    offset = {"Base": 0, "Upside": 1, "Downside": -1}[name]
    return dict(monthly_growth_pct=MONTHLY_GROWTH_PCT + offset,
                approval_rate_pct=PRODUCT_DEFAULTS[product]["approval_rate"] + 3 * offset)


def metrics(frame):
    return {"Revenue": float(frame.revenue.sum()),
            "Provision expense": float(frame.new_provisions.sum()),
            "Net revenue": float(frame.net_revenue.sum()),
            "Originations": float(frame.originations.sum()),
            "Ending CLAB": float(frame.ending_gross_clab.iloc[-1]),
            "Charge-offs": float(frame.charge_offs.sum())}


def evaluate(context):
    risks = build_curves(context["source"], context["settings"], context["empirical"])
    segments = segment_forecasts(context["inputs"], context["share"], risks)
    return combine(segments[b][k] for b in segments for k in context["selected"])


DRIVER_LIMITS = {"monthly_applications_base": (0, 500000), "approval_rate_pct": (0, 100),
                 "avg_loan_size": (100, 100000), "annual_yield_pct": (0, 200),
                 "monthly_growth_pct": (-20, 20), "opening_gross_clab": (0, 1e9)}
CURVE_LIMITS = {"pd": (0, 99), "default_timing": (.25, 4), "payoff_timing": (.25, 4)}
SHIFT_LIMITS = {"pd": (0, 99), "default_shift_months": (-12, 12), "payoff_shift_months": (-12, 12)}
PORTFOLIO_LIMITS = {"creditfresh_share_pct": (0, 100), "line_of_credit_opening_share_pct": (0, 100),
                    "horizon_months": (6, 36)}


def compare_scenario(context, changes):
    """Absolute, validated changes on a copy; never mutate the live model."""
    if not isinstance(changes, list) or not 1 <= len(changes) <= 20:
        raise ValueError("Provide 1–20 assumption changes.")
    trial = deepcopy(context)
    seen = set()
    for change in changes:
        if not isinstance(change, dict) or set(change) != {"target", "field", "value"}:
            raise ValueError("Each change needs target, field and value.")
        target, field, value = change["target"], change["field"], change["value"]
        if not isinstance(target, str) or not isinstance(field, str):
            raise ValueError("Invalid target or field.")
        if (target, field) in seen:
            raise ValueError("Duplicate change.")
        seen.add((target, field))
        limits = (PORTFOLIO_LIMITS if target == "portfolio" else DRIVER_LIMITS if target in trial["inputs"]
                  else (SHIFT_LIMITS if trial["source"] == SYNTHETIC else CURVE_LIMITS) if target in trial["settings"] else {})
        if field not in limits or isinstance(value, bool) or not isinstance(value, (int, float)):
            raise ValueError("Unsupported assumption.")
        lo, hi = limits[field]
        if not math.isfinite(value) or not lo <= value <= hi:
            raise ValueError(f"{field} must be between {lo} and {hi}.")
        if target == "portfolio":
            if field == "creditfresh_share_pct":
                trial["share"] = value / 100
            elif field == "horizon_months":
                if int(value) != value:
                    raise ValueError("Horizon must be an integer.")
                for inputs in trial["inputs"].values():
                    inputs[field] = int(value)
            else:
                if any(c["field"] == "opening_gross_clab" for c in changes):
                    raise ValueError("Change opening balances or the opening split in one preview, not both.")
                total = sum(p["opening_gross_clab"] for p in trial["inputs"].values())
                trial["inputs"]["Line of Credit"]["opening_gross_clab"] = total * value / 100
                trial["inputs"]["Installment"]["opening_gross_clab"] = total * (1 - value / 100)
        elif target in trial["inputs"]:
            trial["inputs"][target][field] = value
        else:
            if field.endswith("_shift_months") and int(value) != value:
                raise ValueError("Timing shifts must be whole months.")
            trial["settings"][target][field] = value
    before, after = evaluate(context), evaluate(trial)
    old, new = metrics(before), metrics(after)
    return {"changes": changes, "view": context["selected"], "currency": "USD",
            "baseline_months": len(before), "preview_months": len(after),
            "baseline": old, "preview": new, "change": {k: new[k]-old[k] for k in old},
            "monthly_preview": after.to_dict(orient="records")}
