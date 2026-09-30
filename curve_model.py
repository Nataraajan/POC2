"""Two explicit curve sources with reversible, term-preserving adjustments."""
import numpy as np
from segments import SEGMENTS

SYNTHETIC = "Synthetic vintage"
MANUAL = "Manual assumptions"
SOURCES = (SYNTHETIC, MANUAL)


def default_settings(source, empirical=None):
    if source not in SOURCES:
        raise ValueError("Unknown curve source")
    return {
        key: dict(
            pd=(empirical[key]["total_default_rate_pct"] if source == SYNTHETIC
                else cfg["lifetime_default"] * 100),
            default_timing=1.0 if source == SYNTHETIC else cfg["default_k"],
            payoff_timing=1.0 if source == SYNTHETIC else cfg["payoff_k"],
        ) for key, cfg in SEGMENTS.items()
    }


def build_curves(source, settings, empirical=None):
    """Manual CDF=(age/term)^k; vintage CDF=observed CDF^k.

    Both conditional event CDFs end at one. PD partitions the population into
    mutually exclusive default and full-payoff outcomes. Payoff is loan closure,
    in addition to scheduled amortization; it is not cumulative cash collection.
    """
    if source not in SOURCES:
        raise ValueError("Unknown curve source")
    result = {}
    for key, cfg in SEGMENTS.items():
        s, term = settings[key], cfg["term_months"]
        if not np.isfinite(s["pd"]) or not 0 <= s["pd"] <= 99:
            raise ValueError("Lifetime default must be between 0 and 99 percent")
        for field in ("default_timing", "payoff_timing"):
            if not np.isfinite(s[field]) or not .25 <= s[field] <= 4:
                raise ValueError("Timing must be between 0.25 and 4")
        base = empirical[key] if source == SYNTHETIC else {}
        if source == SYNTHETIC and base["term_months"] != term:
            raise ValueError("Synthetic source term does not match segment")
        curve = {**base, "term_months": term, "total_default_rate_pct": s["pd"],
                 "midpoint_months": 1.0, "source": source}
        for event in ("default", "payoff"):
            shape = (np.asarray(base[event + "_shape"], dtype=float) if source == SYNTHETIC
                     else np.clip(np.arange(37) / term, 0, 1))
            if (len(shape) != 37 or not np.isfinite(shape).all() or shape[0] != 0
                    or np.any(np.diff(shape) < 0) or np.any(shape < 0)
                    or np.any(shape > 1) or not np.allclose(shape[term:], 1)):
                raise ValueError("Invalid conditional event curve")
            curve[event + "_shape"] = np.power(shape, s[event + "_timing"]).tolist()
        result[key] = curve
    return result
