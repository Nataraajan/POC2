from pathlib import Path
import sys
import numpy as np
import pandas as pd
from streamlit.testing.v1 import AppTest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from clab_forecast_engine_v2 import forecast_clab_v2


def app():
    at = AppTest.from_file(str(ROOT / "app.py"), default_timeout=30).run()
    assert not at.exception
    return at


def forecast(at):
    assert not at.exception
    return at.dataframe[1].value


def test_default_matches_existing_engine():
    at = app()
    expected = forecast_clab_v2(30000, [1.0] * 12, 30, 1500, 100, 2, 12, 12, 24)
    actual = forecast(at)
    np.testing.assert_allclose(actual.to_numpy(), expected.to_numpy(), rtol=1e-12)
    assert at.metric[0].value == "$147.39M"


def test_driver_changes_and_product_persistence():
    at = app()
    initial = forecast(at).copy()
    at.number_input(key="driver_Short-Term_apps").set_value(60000).run()
    changed = forecast(at).copy()
    np.testing.assert_allclose(changed.iloc[:, 1:], initial.iloc[:, 1:] * 2)
    at.radio(key="portfolio").set_value("Installment").run()
    installment = forecast(at).copy()
    at.radio(key="portfolio").set_value("Combined").run()
    np.testing.assert_allclose(
        forecast(at).iloc[:, 1:], changed.iloc[:, 1:] + installment.iloc[:, 1:]
    )
    at.radio(key="portfolio").set_value("Short-Term").run()
    assert at.number_input(key="driver_Short-Term_apps").value == 60000


def test_apply_curve_and_restore_manual():
    at = app()
    at.slider(key="driver_Short-Term_rate").set_value(20.0).run()
    manual = forecast(at).copy()
    next(b for b in at.button if b.label == "Apply historical curve").click().run()
    assert at.radio(key="driver_source").value == "Historical vintage"
    assert at.slider(key="driver_Short-Term_rate").disabled
    assert not np.allclose(forecast(at)["Revenue"], manual["Revenue"])
    next(b for b in at.button if b.label == "Use manual assumptions").click().run()
    pd.testing.assert_frame_equal(forecast(at), manual)
    assert at.slider(key="driver_Short-Term_rate").value == 20.0


def test_reconciliation_quarters_and_reset():
    at = app()
    at.radio(key="portfolio").set_value("Combined").run()
    at.slider(key="driver_horizon").set_value(25).run()
    f = forecast(at)
    np.testing.assert_allclose(
        f["Closing gross CLAB"],
        f["Opening gross CLAB"]
        + f["Originations"]
        - f["Principal repayments"]
        - f["Charge-offs"],
    )
    np.testing.assert_allclose(
        f["Closing reserve"],
        f["Opening reserve"] + f["Provision expense"] - f["Charge-offs"],
    )
    np.testing.assert_allclose(f["Net revenue"], f["Revenue"] - f["Provision expense"])
    next(r for r in at.radio if r.label == "Table period").set_value("Quarterly").run()
    assert len(forecast(at)) == 8
    assert np.isclose(forecast(at).Revenue.sum(), f.Revenue.iloc[:24].sum())
    next(b for b in at.button if b.label == "Reset drivers").click().run()
    assert not at.exception
    assert at.slider(key="driver_horizon").value == 24


def test_zero_originations_and_zero_yield():
    at = app()
    at.number_input(key="driver_Short-Term_apps").set_value(0).run()
    assert np.allclose(forecast(at).iloc[:, 1:], 0)
    at.number_input(key="driver_Short-Term_apps").set_value(30000).run()
    at.slider(key="driver_Short-Term_yield").set_value(0.0).run()
    assert np.allclose(forecast(at).Revenue, 0)


def test_vintage_app_smoke():
    at = AppTest.from_file(str(ROOT / "vintage_app.py"), default_timeout=30).run()
    assert not at.exception
