from copy import deepcopy
import json
from unittest.mock import patch
from urllib.error import HTTPError, URLError
import pandas as pd
import pytest
from test_dashboard import app, full
import ai_chat
from scenario_tools import compare_scenario, evaluate, preset_values


@pytest.fixture(scope='module')
def context():
    return deepcopy(app().session_state['ai_context'])


def test_allocation_preserves_total_and_exports(monkeypatch):
    import excel_export
    snapshots = []
    monkeypatch.setattr(excel_export, 'export_model', lambda x: snapshots.append(x) or b'xlsx')
    at = app()
    total = full(at)['Opening gross CLAB'].iloc[0]
    original = full(at).copy()
    at.slider(key='driver_line_of_credit_share').set_value(50.0).run()
    assert not at.exception
    assert full(at)['Opening gross CLAB'].iloc[0] == pytest.approx(total)
    assert at.session_state['driver_Line of Credit_opening'] == pytest.approx(total/2)
    assert at.session_state['driver_Installment_opening'] == pytest.approx(total/2)
    assert at.session_state['scenario'] == 'Custom'
    pd.testing.assert_series_equal(full(at).Originations, original.Originations)
    at.button(key='prepare_excel').click().run()
    assert snapshots[-1]['products']['Line of Credit']['active']['opening_gross_clab'] == pytest.approx(total/2)
    at.button(key='restore_opening_split').click().run()
    pd.testing.assert_frame_equal(full(at), original)
    for split in (0.0, 100.0):
        at.slider(key='driver_line_of_credit_share').set_value(split).run()
        assert not at.exception
        assert full(at)['Opening gross CLAB'].iloc[0] == pytest.approx(total)


def test_scenarios_compare_without_mutating_live_inputs():
    at = app()
    at.number_input(key='driver_Line of Credit_apps').set_value(75000).run()
    before = full(at).copy()
    at.button(key='compare_scenarios_button').click().run()
    assert not at.exception
    pd.testing.assert_frame_equal(full(at), before)
    comparison = at.table[-1].value
    assert list(comparison.index) == ['Current · Custom', 'Base', 'Upside', 'Downside']
    next(b for b in at.button if b.label == 'Upside').click().run()
    assert at.session_state['scenario'] == 'Upside'
    assert full(at).Revenue.sum()/1e6 == pytest.approx(comparison.loc['Upside', 'Revenue'])
    assert not any('ACTIVE SCENARIO:' in m.value for m in at.markdown)
    assert any('.st-key-scenario_Upside button {background:#0078d9' in m.value for m in at.markdown)
    assert 'Monthly schedule' not in at.radio(key='navigation').options


def test_preview_matches_engine_and_never_changes_inputs(context):
    saved = deepcopy(context)
    changes = [{'target': 'Line of Credit', 'field': 'monthly_applications_base', 'value': 100000},
               {'target': 'portfolio', 'field': 'line_of_credit_opening_share_pct', 'value': 50}]
    preview = compare_scenario(context, changes)
    trial = deepcopy(context)
    trial['inputs']['Line of Credit']['monthly_applications_base'] = 100000
    total = sum(v['opening_gross_clab'] for v in trial['inputs'].values())
    for inputs in trial['inputs'].values(): inputs['opening_gross_clab'] = total/2
    assert preview['preview']['Revenue'] == pytest.approx(evaluate(trial).revenue.sum())
    assert context == saved


@pytest.mark.parametrize('change', [
    {'target': 'portfolio', 'field': 'creditfresh_share_pct', 'value': float('nan')},
    {'target': 'portfolio', 'field': 'creditfresh_share_pct', 'value': 101},
    {'target': 'portfolio', 'field': 'horizon_months', 'value': 12.5},
    {'target': 'Line of Credit', 'field': 'term_months', 'value': 24},
    {'target': '__import__', 'field': 'execute', 'value': 1},
    {'target': 'Line of Credit', 'field': 'annual_yield_pct', 'value': True},
])
def test_invalid_ai_changes_rejected(context, change):
    with pytest.raises(ValueError): compare_scenario(context, [change])


def test_openai_tool_roundtrip(context):
    calls = []
    def fake(payload, key):
        calls.append(deepcopy(payload))
        assert payload['store'] is False
        assert 'secret-key' not in json.dumps(payload)
        if len(calls) == 1:
            return {'output': [{'type': 'function_call', 'call_id': 'c1', 'name': 'compare_scenario',
                'arguments': json.dumps({'changes': [{'target': 'portfolio', 'field': 'creditfresh_share_pct', 'value': 60}]})}]}
        assert payload['input'][-1]['type'] == 'function_call_output'
        result = json.loads(payload['input'][-1]['output'])
        assert 'preview' in result
        return {'output': [{'type': 'message', 'content': [{'type': 'output_text', 'text': 'Calculated preview.'}]}]}
    text, previews = ai_chat.answer('What if CreditFresh is 60%?', [], context, 'secret-key', 'model', fake)
    assert text == 'Calculated preview.' and len(previews) == 1
    assert len(calls) == 2


def test_api_failure_hides_sensitive_response():
    error = HTTPError('https://api.openai.com', 401, 'secret detail', {}, None)
    with patch.object(ai_chat, 'urlopen', side_effect=error):
        with pytest.raises(RuntimeError, match='key needs updating') as caught:
            ai_chat.api_response({}, 'secret-key')
        assert 'secret' not in str(caught.value)
    with patch.object(ai_chat, 'urlopen', side_effect=URLError('network')):
        with pytest.raises(RuntimeError, match='could not be reached'):
            ai_chat.api_response({}, 'secret-key')


def test_widget_visible_and_missing_key_graceful(monkeypatch):
    monkeypatch.setattr(ai_chat, 'server_setting', lambda *args: '')
    at = app()
    assert at.button(key='ai_toggle').label == '✦ Ask AI'
    at.button(key='ai_toggle').click().run()
    assert not at.exception
    assert at.chat_input(key='model_chat').disabled
    assert any('AI setup required' in i.value for i in at.info)
    before = full(at).copy()
    at.button(key='ai_toggle').click().run()
    pd.testing.assert_frame_equal(full(at), before)


def application_window(target='Line of Credit', start=1, end=7, value=2):
    return dict(target=target, field='applications_change_pct', value=value,
                start_month=start, end_month=end)


def test_temporary_uplift_does_not_repeat_and_year_two_isolated(context):
    saved = deepcopy(context)
    result = compare_scenario(context, [application_window(t) for t in context['selected']])
    a, b = pd.DataFrame(result['monthly_baseline']), pd.DataFrame(result['monthly_preview'])
    for field in ('applications', 'originations', 'new_provisions'):
        assert b[field].iloc[:7].to_numpy() == pytest.approx(a[field].iloc[:7].to_numpy()*1.02)
        assert b[field].iloc[7:].to_numpy() == pytest.approx(a[field].iloc[7:].to_numpy())
    assert b.revenue.iloc[0] == pytest.approx(a.revenue.iloc[0])  # new lending earns next month
    y2 = result['annual_comparison'][1]
    assert y2['complete_year']
    assert y2['baseline']['Revenue'] == pytest.approx(a.revenue.iloc[12:24].sum())
    assert y2['change']['Revenue'] == pytest.approx((b.revenue-a.revenue).iloc[12:24].sum())
    assert 0 < y2['change']['Revenue'] < result['change']['Revenue']
    assert sum(p['change']['Revenue'] for p in result['annual_comparison']) == pytest.approx(result['change']['Revenue'])
    assert context == saved


@pytest.mark.parametrize('start,end', [(7,7), (7,24), (1,7)])
def test_window_boundaries(context, start, end):
    result = compare_scenario(context, [application_window(start=start, end=end)])
    a, b = pd.DataFrame(result['monthly_baseline']), pd.DataFrame(result['monthly_preview'])
    changed = (b.applications-a.applications).abs() > .001
    assert changed.tolist() == [start <= m <= end for m in a.month]


@pytest.mark.parametrize('changes', [
    [application_window(start=0)], [application_window(start=8, end=7)],
    [application_window(start=True)], [application_window(end=7.5)],
    [application_window(end=25)], [application_window(value=-101)],
    [application_window(value=float('nan'))], [application_window(value=True)],
    [application_window(), application_window(start=7,end=9)],
    [application_window(), dict(target='Line of Credit', field='monthly_applications_base', value=90000)],
    [dict(target='Line of Credit', field='annual_yield_pct', value=90, start_month=1, end_month=7)],
])
def test_invalid_timed_scenarios(context, changes):
    with pytest.raises(ValueError): compare_scenario(context, changes)


def test_disjoint_windows_and_partial_year(context):
    c = deepcopy(context)
    for inputs in c['inputs'].values(): inputs['horizon_months'] = 18
    result = compare_scenario(c, [application_window(end=2), application_window(start=5,end=7)])
    assert not result['annual_comparison'][1]['complete_year']
    assert result['annual_comparison'][1]['preview_months'] == 6
    extended = compare_scenario(c, [application_window(), dict(target='portfolio', field='horizon_months', value=24)])
    assert extended['baseline_months'] == extended['preview_months'] == 24
    assert extended['annual_comparison'][1]['complete_year']


def test_timed_tool_roundtrip_and_readable_details(context):
    calls = []
    def fake(payload, key):
        calls.append(payload)
        if len(calls) == 1:
            assert 'Resolve ambiguous timing BEFORE' in payload['instructions']
            return {'output': [{'type': 'function_call', 'call_id': 'window', 'name': 'compare_scenario',
                'arguments': json.dumps({'changes': [application_window(t) for t in context['selected']]})}]}
        result = json.loads(payload['input'][-1]['output'])
        assert result['annual_comparison'][1]['baseline']['Revenue'] > 0
        return {'output': [{'type': 'message', 'content': [{'type': 'output_text', 'text': 'Year 2 calculated.'}]}]}
    text, previews = ai_chat.answer('Applications +2% only in months 1-7. Year 2 revenue?', [], context, 'fake', 'model', fake)
    assert text == 'Year 2 calculated.'
    assert 'months 1–7 only' in ai_chat.describe_change(previews[0]['changes'][0])
    assert 'monthly_applications_base' not in ai_chat.describe_change(dict(target='Installment', field='monthly_applications_base', value=40000))
