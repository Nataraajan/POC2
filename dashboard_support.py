"""Formatting and historical-data loader retained from the original dashboard."""

import pandas as pd
import streamlit as st
from generate_loan_data import PRODUCTS as HIST_PRODUCTS
from derive_vintage_curves import (
    LOANS_CSV,
    load_into_sqlite,
    build_vintage_triangle,
    pooled_default_curve,
    fit_default_curve,
)

BLUE = "#2563EB"


RED = "#DC2626"


def _fmt_dollar_scaled(val):
    """Same auto-scaling convention as the SaaS revenue model."""
    if val is None or pd.isna(val):
        return "—"
    sign = "−" if val < 0 else ""
    val = abs(val)
    if val >= 1_000_000:
        return f"{sign}${val / 1_000_000:,.2f}M"
    if val >= 1_000:
        return f"{sign}${val / 1_000:,.2f}K"
    return f"{sign}${val:,.0f}"


DOLLAR_COLS = [
    "originations",
    "beginning_gross_clab",
    "principal_repaid",
    "charge_offs",
    "ending_gross_clab",
    "new_provisions",
    "beginning_reserve",
    "ending_reserve",
    "net_clab",
    "revenue",
    "net_revenue",
]


def gross_reserve_net_display(gross, reserve):
    """Gross, Reserve and Net formatted in one shared unit (the gross figure's), with the
    displayed Net taken from the displayed Gross and Reserve — so the three always foot
    on screen, instead of rounding independently and appearing to be off by $0.01M."""
    divisor, suffix = (
        (1_000_000, "M")
        if abs(gross) >= 1_000_000
        else (1_000, "K") if abs(gross) >= 1_000 else (1, "")
    )
    decimals = 2 if divisor > 1 else 0
    gross_shown, reserve_shown = round(gross / divisor, decimals), round(
        reserve / divisor, decimals
    )

    def fmt(v):
        return f"{'−' if v < 0 else ''}${abs(v):,.{decimals}f}{suffix}"

    return (
        fmt(gross_shown),
        fmt(reserve_shown),
        fmt(round(gross_shown - reserve_shown, decimals)),
    )


@st.cache_data
def load_vintage_data():
    """Loads the loan-level history once, builds the vintage triangle in SQL,
    and fits one default curve per product. Cached — reruns from moving a
    slider don't repeat any of it."""
    loans_df = pd.read_csv(LOANS_CSV)
    conn = load_into_sqlite(loans_df)
    triangle = build_vintage_triangle(conn)
    conn.close()
    fits = {
        p: fit_default_curve(pooled_default_curve(triangle, p)) for p in HIST_PRODUCTS
    }
    return len(loans_df), triangle, fits


PRODUCT_DEFAULTS = {
    "Short-Term": dict(
        applications=30000,
        approval_rate=30.0,
        avg_loan_size=1500.0,
        annual_yield=100.0,
        term_months=12,
        days_to_default=60,
        total_default_rate=12.0,
        color=RED,
    ),
    "Installment": dict(
        applications=12000,
        approval_rate=45.0,
        avg_loan_size=4000.0,
        annual_yield=55.0,
        term_months=24,
        days_to_default=150,
        total_default_rate=6.0,
        color=BLUE,
    ),
}
