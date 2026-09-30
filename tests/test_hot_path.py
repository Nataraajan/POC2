"""Hot-path regressions: cache reuse, invalidation and on-demand rendering."""
from unittest.mock import patch
import pandas as pd
import streamlit as st
from test_dashboard import app, full
import product_forecast


def test_cache_reuse_and_each_forecast_input_invalidates():
    st.cache_data.clear()
    with patch.object(product_forecast, 'segment_forecasts', wraps=product_forecast.segment_forecasts) as run:
        at = app()
        original = full(at).copy()
        assert run.call_count == 1  # no second manual forecast
        at.run()
        assert run.call_count == 1
        pd.testing.assert_frame_equal(full(at), original)
        for key, value in [('driver_Short-Term_apps', 95000),
                           ('driver_creditfresh_mix', 60.0),
                           ('driver_horizon', 30),
                           ('driver_curve_Synthetic vintage_CreditFresh Short-Term_pd', 40.0)]:
            before = run.call_count
            at.number_input(key=key).set_value(value).run()
            assert not at.exception
            assert run.call_count == before + 1
        at.toggle(key='show_manual_comparison').set_value(True).run()
        assert run.call_count == 6
        at.toggle(key='show_manual_comparison').set_value(False).run()
        assert run.call_count == 6


def test_charts_render_only_when_requested_in_their_section():
    at = app()
    assert not at.get('plotly_chart')
    at.toggle(key='show_revenue_chart').set_value(True).run()
    assert not at.exception
    assert len(at.get('plotly_chart')) == 1
    at.toggle(key='show_applied_chart').set_value(True).run()
    assert not at.exception
    assert len(at.get('plotly_chart')) == 2
    at.radio(key='navigation').set_value('Model assumptions').run()
    assert not at.get('plotly_chart')
    with patch.object(product_forecast, 'segment_forecasts', side_effect=AssertionError('Vintage must not forecast')):
        at.radio(key='navigation').set_value('Vintage Analysis & Overlay').run()
        assert not at.exception
        assert not at.get('plotly_chart')
        at.toggle(key='show_vintage_chart').set_value(True).run()
        assert not at.exception
        assert len(at.get('plotly_chart')) == 1
