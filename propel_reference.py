"""Public volume anchors, separate from hypothetical segment credit assumptions.

Reviewed 2026-09-30. All monetary amounts are USD.
"""
AS_OF = "2026-06-30"
SOURCE_2024 = "https://cdn.propelholdings.com/web/pdfs/2024PropelQ4MDA.pdf"
SOURCE_2025 = "https://cdn.propelholdings.com/web/pdfs/2025PropelQ4MDA.pdf"
SOURCE_LATEST = "https://cdn.propelholdings.com/web/pdfs/2026PropelQ2MDA.pdf"
HISTORY = [
    dict(period="FY2024", months=12, clab=480602408, prior_clab=337282804,
         originations=586436066, prior_originations=412613761, revenue=449730785, source=SOURCE_2024),
    dict(period="FY2025", months=12, clab=589548106, prior_clab=480602408,
         originations=774263664, prior_originations=586436066, revenue=589807759, source=SOURCE_2025),
    dict(period="Q2 2026", months=3, clab=639083326, prior_clab=520403519,
         originations=243423212, prior_originations=194394548, revenue=179604747, source=SOURCE_LATEST),
]
LATEST = HISTORY[-1]
OPENING_CLAB = LATEST["clab"]
MONTHLY_FUNDING = LATEST["originations"] / LATEST["months"]
CLAB_GROWTH = LATEST["clab"] / LATEST["prior_clab"] - 1
# Extrapolation of same-quarter YoY funded-dollar growth; not company guidance.
MONTHLY_GROWTH_PCT = ((LATEST["originations"] / LATEST["prior_originations"]) ** (1 / 12) - 1) * 100
APPLICATIONS = {"Line of Credit": 89286, "Installment": 35714}
OPENING_SHARES = {"Line of Credit": .4, "Installment": .6}
# Scale illustrative conversion rates to the reported quarterly monthly average.
# This is an effective funding conversion, not an estimate of actual approvals.
FUNDING_SCALE = MONTHLY_FUNDING / (89286 * .30 * 1500 + 35714 * .45 * 4000)
APPROVALS = {"Line of Credit": 30 * FUNDING_SCALE, "Installment": 45 * FUNDING_SCALE}


def reference_path(months):
    """Historical CLAB growth extrapolated as a comparison, never a forecast plug."""
    return [OPENING_CLAB * (1 + CLAB_GROWTH) ** (m / 12) for m in range(1, months + 1)]
