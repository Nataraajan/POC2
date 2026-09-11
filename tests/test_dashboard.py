from pathlib import Path
import sys
import numpy as np
import pandas as pd
import pytest
from streamlit.testing.v1 import AppTest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from clab_forecast_engine_v2 import (
    forecast_clab_v2,
    cumulative_default_pct,
    remaining_principal_fraction,
)


def app():
    at = AppTest.from_file(str(ROOT / "app.py"), default_timeout=30).run()
    assert not at.exception
    return at


def full(at):
    assert not at.exception
    return at.dataframe[1].value


def engine(**changes):
    args = dict(
        monthly_applications_base=30000,
        seasonality_pattern=[1.0] * 12,
        approval_rate_pct=30.0,
        avg_loan_size=1500.0,
        annual_yield_pct=100.0,
        midpoint_months=2.0,
        total_default_rate_pct=12.0,
        term_months=12,
        horizon_months=24,
    )
    args.update(changes)
    return forecast_clab_v2(**args)


def test_legacy_empty_book_regression():
    expected = pd.read_csv(ROOT / "tests/legacy_forecast.csv")
    np.testing.assert_allclose(
        engine().to_numpy(), expected.to_numpy(), rtol=1e-12, atol=1e-7
    )


@pytest.mark.parametrize("age", [0, 3, None])
@pytest.mark.parametrize("yield_pct", [0.0, 100.0])
def test_opening_cohorts_run_off_and_reserve_is_not_expensed(age, yield_pct):
    f = engine(
        monthly_applications_base=0,
        opening_gross_clab=639e6,
        opening_age_months=age,
        annual_yield_pct=yield_pct,
    )
    assert f.beginning_gross_clab.iloc[0] == 639e6
    assert np.allclose(f.new_provisions, 0)
    assert f.beginning_reserve.iloc[0] > 0
    np.testing.assert_allclose(f.principal_repaid.sum() + f.charge_offs.sum(), 639e6)
    assert abs(f.ending_gross_clab.iloc[-1]) < 1e-5
    assert abs(f.ending_reserve.iloc[-1]) < 1e-5
    np.testing.assert_allclose(f.beginning_reserve.iloc[0], f.charge_offs.sum())
    np.testing.assert_allclose(
        f.revenue,
        (f.beginning_gross_clab - f.charge_offs) * yield_pct / 1200,
        atol=1e-7,
    )
    assert f.revenue.iloc[0] > 0 if yield_pct else f.revenue.iloc[0] == 0


def test_opening_survivors_independent_first_month_calculation():
    # Known cohort at MOB 3: condition defaults on survival and scheduled
    # principal on its remaining balance, independently of convolution.
    amount = 50e6
    f = engine(
        opening_gross_clab=amount, opening_age_months=3, monthly_applications_base=0
    )
    d3 = cumulative_default_pct(3, 2, 12) / 100
    d4 = cumulative_default_pct(4, 2, 12) / 100
    b3 = remaining_principal_fraction(3, 12, 100)
    b4 = remaining_principal_fraction(4, 12, 100)
    loss = amount * (d4 - d3) / (1 - d3)
    repaid = amount * (1 - (d4 - d3) / (1 - d3)) * (1 - b4 / b3)
    np.testing.assert_allclose(f.charge_offs.iloc[0], loss)
    np.testing.assert_allclose(f.principal_repaid.iloc[0], repaid)
    np.testing.assert_allclose(f.ending_gross_clab.iloc[0], amount - loss - repaid)


def test_default_portfolio_uses_639m_and_month_one_revenue():
    at = app()
    f = full(at)
    assert f["Opening gross CLAB"].iloc[0] == 639e6
    assert f.Revenue.iloc[0] > 0
    assert f["Net revenue"].iloc[0] > 0
    assert f["Opening reserve"].iloc[0] > 0
    np.testing.assert_allclose(
        f["Gross CLAB"],
        f["Opening gross CLAB"]
        + f.Originations
        - f["Principal repayments"]
        - f["Charge-offs"],
    )
    np.testing.assert_allclose(
        f.Reserve, f["Opening reserve"] + f["Provision expense"] - f["Charge-offs"]
    )
    np.testing.assert_allclose(f["Net revenue"], f.Revenue - f["Provision expense"])


def test_product_persistence_and_combined_totals():
    at = app()
    at.selectbox(key="portfolio").set_value("Short-Term").run()
    at.number_input(key="driver_Short-Term_apps").set_value(60000).run()
    short = full(at).copy()
    at.selectbox(key="portfolio").set_value("Installment").run()
    installment = full(at).copy()
    at.selectbox(key="portfolio").set_value("Combined").run()
    np.testing.assert_allclose(
        full(at).iloc[:, 1:], short.iloc[:, 1:] + installment.iloc[:, 1:]
    )
    at.selectbox(key="portfolio").set_value("Short-Term").run()
    assert at.number_input(key="driver_Short-Term_apps").value == 60000


def test_historical_switch_and_restore():
    at = app()
    at.number_input(key="driver_Short-Term_rate").set_value(20.0).run()
    manual = full(at).copy()
    next(b for b in at.button if b.label == "Apply historical curve").click().run()
    assert at.selectbox(key="driver_source").value == "Historical vintage"
    assert not np.allclose(full(at).Revenue, manual.Revenue)
    at.selectbox(key="driver_source").set_value("Manual assumptions").run()
    pd.testing.assert_frame_equal(full(at), manual)
    assert at.number_input(key="driver_Short-Term_rate").value == 20.0


def test_growth_scenarios_reset_and_partial_quarter():
    at = app()
    next(b for b in at.button if b.label == "Upside").click().run()
    assert full(at).Applications.iloc[1] > full(at).Applications.iloc[0]
    at.number_input(key="driver_horizon").set_value(25).run()
    f = full(at).copy()
    next(r for r in at.radio if r.label == "Table period").set_value("Quarterly").run()
    assert len(full(at)) == 8
    np.testing.assert_allclose(full(at).Revenue.sum(), f.Revenue.iloc[:24].sum())
    next(b for b in at.button if b.label == "Reset").click().run()
    assert at.number_input(key="driver_horizon").value == 24
    assert at.number_input(key="driver_Short-Term_opening_m").value == 255.6


def test_term_one_and_single_age():
    at = app()
    at.number_input(key="driver_Short-Term_term").set_value(1).run()
    assert not at.exception
    at.selectbox(key="driver_Short-Term_age_mix").set_value(
        "Single cohort at specified MOB"
    ).run()
    assert not at.exception
    assert at.number_input(key="driver_Short-Term_age").value == 0


def test_invalid_opening_age():
    with pytest.raises(ValueError):
        engine(opening_gross_clab=1e6, opening_age_months=12)


def test_vintage_app_smoke():
    at = AppTest.from_file(str(ROOT / "vintage_app.py"), default_timeout=30).run()
    assert not at.exception


def test_navigation_preserves_forecast():
    at = app()
    at.number_input(key="driver_Short-Term_apps").set_value(60000).run()
    at.selectbox(key="driver_source").set_value("Historical vintage").run()
    expected = full(at).copy()
    for page in ["Monthly schedule", "Vintage analysis", "Model assumptions"]:
        at.radio(key="navigation").set_value(page).run()
        assert not at.exception
        assert at.radio(key="navigation").value == page
    at.radio(key="navigation").set_value("Forecasting").run()
    assert at.number_input(key="driver_Short-Term_apps").value == 60000
    assert at.selectbox(key="driver_source").value == "Historical vintage"
    pd.testing.assert_frame_equal(full(at), expected)


def test_annual_kpis_and_partial_year():
    at = app()
    cards = next(m.value for m in at.markdown if 'class="kpi-grid"' in m.value)
    assert "$421.20M" in cards  # 35.1M originations x 12, not a monthly KPI
    assert cards.count("Year 1 ·") == 6 and cards.count("Year 2 ·") == 6
    assert "PLL / provision expense" in cards
    assert "Charge-offs" not in cards
    at.number_input(key="driver_horizon").set_value(18).run()
    cards = next(m.value for m in at.markdown if 'class="kpi-grid"' in m.value)
    assert cards.count("requires 24 forecast months") == 6


def test_horizontal_schedule_reconciles():
    at = app()
    schedule = at.dataframe[0].value
    assert list(schedule.columns) == [f"Month {m}" for m in range(1, 25)]
    np.testing.assert_allclose(schedule.loc["CreditFresh revenue"] + schedule.loc["MoneyKey revenue"], schedule.loc["Revenue"])
    np.testing.assert_allclose(schedule.loc["Revenue"].to_numpy()*1e6, full(at).Revenue)
    np.testing.assert_allclose(schedule.loc["Applications"].to_numpy(), full(at).Applications)


def test_opening_millions_converts_to_engine_dollars():
    at = app()
    at.number_input(key="driver_Short-Term_opening_m").set_value(300.0).run()
    assert not at.exception
    assert at.session_state["driver_Short-Term_opening"] == 300_000_000
    assert full(at)["Opening gross CLAB"].iloc[0] == 683_400_000


def test_embedded_vintage_walkthrough_and_handoff():
    at = app()
    at.radio(key="navigation").set_value("Vintage analysis").run()
    assert not at.exception
    assert len(at.code) == 2  # displayed SQL queries
    assert len(at.dataframe) >= 4  # validation, sample rows, curve, triangle
    next(b for b in at.button if b.label == "Run live demo").click().run(timeout=60)
    assert not at.exception
    expected = at.session_state["live_demo_run"]["overlay"].copy()
    next(b for b in at.button if b.label == "Preview this live curve in forecast overlay").click().run()
    assert not at.exception
    assert at.radio(key="navigation").value == "Vintage overlay"
    pd.testing.assert_frame_equal(at.session_state["overlay_experiment_result"]["overlay"], expected)


def test_vintage_experiment_applies_to_forecast():
    at = app()
    before = full(at).copy()
    at.radio(key="navigation").set_value("Vintage overlay").run()
    next(n for n in at.number_input if n.label == "CreditFresh lifetime default (%)").set_value(35.0)
    next(b for b in at.button if b.label == "Generate vintage curves").click().run(timeout=60)
    assert not at.exception
    at.selectbox(key="overlay_map_Short-Term").set_value("CreditFresh").run()
    at.selectbox(key="overlay_map_Installment").set_value("MoneyKey").run()
    next(b for b in at.button if b.label == "Apply overlay to forecast").click().run()
    assert not at.exception
    at.radio(key="navigation").set_value("Forecasting").run()
    assert at.selectbox(key="driver_source").value == "Historical vintage"
    assert not np.allclose(before["Provision expense"], full(at)["Provision expense"])


def test_editable_brand_mix():
    at = app()
    total = full(at).Revenue.copy()
    schedule = at.dataframe[0].value
    np.testing.assert_allclose(schedule.loc["CreditFresh revenue"], schedule.loc["Revenue"]*.8)
    at.number_input(key="driver_creditfresh_mix").set_value(65.0).run()
    schedule = at.dataframe[0].value
    np.testing.assert_allclose(schedule.loc["CreditFresh revenue"], schedule.loc["Revenue"]*.65)
    np.testing.assert_allclose(schedule.loc["MoneyKey revenue"], schedule.loc["Revenue"]*.35)
    np.testing.assert_allclose(full(at).Revenue, total)
