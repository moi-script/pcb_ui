from __future__ import annotations

import pytest

from grbl.protocol import State, Status, parse_status, resolve_positions


def test_parses_minimal_idle_report():
    s = parse_status("<Idle|MPos:0.000,0.000,0.000|FS:0,0>")
    assert s is not None
    assert s.state is State.IDLE
    assert s.substate is None
    assert s.mpos == (0.0, 0.0, 0.0)
    assert s.wpos is None
    assert s.wco is None
    assert s.feed == 0.0
    assert s.spindle == 0.0


def test_parses_full_run_report():
    s = parse_status(
        "<Run|MPos:124.500,62.858,5.000|FS:800,0"
        "|WCO:100.000,50.000,0.000|Ov:100,100,100|Pn:XY>"
    )
    assert s is not None
    assert s.state is State.RUN
    assert s.mpos == (124.5, 62.858, 5.0)
    assert s.wco == (100.0, 50.0, 0.0)
    assert s.feed == 800.0
    assert s.ov == (100, 100, 100)
    assert s.pins == "XY"


def test_parses_hold_substate():
    s = parse_status("<Hold:0|MPos:1.000,2.000,3.000|FS:0,0>")
    assert s is not None
    assert s.state is State.HOLD
    assert s.substate == 0


def test_parses_wpos_variant():
    """Controllers with the $10 mask set to work coords report WPos, not MPos."""
    s = parse_status("<Idle|WPos:10.000,20.000,1.000|FS:0,0>")
    assert s is not None
    assert s.wpos == (10.0, 20.0, 1.0)
    assert s.mpos is None


def test_parses_alarm_state():
    s = parse_status("<Alarm|MPos:0.000,0.000,0.000|FS:0,0>")
    assert s is not None
    assert s.state is State.ALARM


def test_ignores_non_status_lines():
    assert parse_status("ok") is None
    assert parse_status("error:15") is None
    assert parse_status("[MSG:Reset to continue]") is None
    assert parse_status("") is None


def test_resolve_uses_reported_wco():
    s = parse_status("<Run|MPos:124.500,62.858,5.000|FS:0,0|WCO:100.000,50.000,0.000>")
    assert s is not None
    mpos, wpos, wco = resolve_positions(s, None)
    assert mpos == (124.5, 62.858, 5.0)
    assert wpos == pytest.approx((24.5, 12.858, 5.0))
    assert wco == (100.0, 50.0, 0.0)


def test_resolve_uses_cached_wco_when_report_omits_it():
    """WCO is only sent every ~10th report. Without the cache the DRO jumps."""
    s = parse_status("<Run|MPos:125.000,62.858,5.000|FS:0,0>")
    assert s is not None
    mpos, wpos, wco = resolve_positions(s, (100.0, 50.0, 0.0))
    assert mpos == (125.0, 62.858, 5.0)
    assert wpos == pytest.approx((25.0, 12.858, 5.0))
    assert wco == (100.0, 50.0, 0.0)


def test_resolve_assumes_zero_wco_when_never_seen():
    s = parse_status("<Idle|MPos:5.000,5.000,5.000|FS:0,0>")
    assert s is not None
    mpos, wpos, wco = resolve_positions(s, None)
    assert wco == (0.0, 0.0, 0.0)
    assert wpos == (5.0, 5.0, 5.0)


def test_resolve_derives_mpos_from_wpos_variant():
    s = parse_status("<Idle|WPos:10.000,20.000,1.000|FS:0,0>")
    assert s is not None
    mpos, wpos, wco = resolve_positions(s, (3.0, 4.0, 0.0))
    assert wpos == (10.0, 20.0, 1.0)
    assert mpos == pytest.approx((13.0, 24.0, 1.0))
