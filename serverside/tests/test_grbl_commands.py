from __future__ import annotations

from grbl.protocol import (
    ALARM_MESSAGES,
    ERROR_MESSAGES,
    Realtime,
    encode_jog,
    encode_zero,
    fmt,
    parse_reply,
)


def test_realtime_bytes_are_single_bytes():
    for name in (
        "STATUS", "FEED_HOLD", "RESUME", "SOFT_RESET", "JOG_CANCEL",
        "SAFETY_DOOR", "FEED_100", "RAPID_100",
    ):
        value = getattr(Realtime, name)
        assert isinstance(value, bytes)
        assert len(value) == 1


def test_realtime_byte_values_match_the_protocol():
    assert Realtime.STATUS == b"?"
    assert Realtime.FEED_HOLD == b"!"
    assert Realtime.RESUME == b"~"
    assert Realtime.SOFT_RESET == b"\x18"
    assert Realtime.JOG_CANCEL == b"\x85"


def test_parse_ok():
    r = parse_reply("ok")
    assert r is not None and r.kind == "ok" and r.code is None


def test_parse_error_carries_human_text():
    r = parse_reply("error:15")
    assert r is not None
    assert r.kind == "error"
    assert r.code == 15
    assert "Travel exceeded" in r.text or "travel" in r.text.lower()


def test_parse_unknown_error_code_still_returns_error():
    r = parse_reply("error:999")
    assert r is not None
    assert r.kind == "error"
    assert r.code == 999
    assert "999" in r.text


def test_parse_alarm_carries_human_text():
    r = parse_reply("ALARM:2")
    assert r is not None
    assert r.kind == "alarm"
    assert r.code == 2
    assert r.text


def test_parse_message():
    r = parse_reply("[MSG:Reset to continue]")
    assert r is not None
    assert r.kind == "message"
    assert r.text == "Reset to continue"


def test_parse_banner():
    r = parse_reply("Grbl 1.1h ['$' for help]")
    assert r is not None
    assert r.kind == "banner"
    assert "1.1h" in r.text


def test_parse_setting_line():
    r = parse_reply("$100=80.000")
    assert r is not None
    assert r.kind == "settings"
    assert r.text == "$100=80.000"


def test_status_reports_are_not_replies():
    assert parse_reply("<Idle|MPos:0.000,0.000,0.000|FS:0,0>") is None


def test_blank_lines_are_not_replies():
    assert parse_reply("") is None
    assert parse_reply("   ") is None


def test_error_table_covers_the_common_codes():
    for code in (1, 2, 3, 9, 15, 20, 24, 25):
        assert code in ERROR_MESSAGES
        assert ERROR_MESSAGES[code]


def test_alarm_table_covers_the_common_codes():
    for code in (1, 2, 3, 9):
        assert code in ALARM_MESSAGES
        assert ALARM_MESSAGES[code]


def test_fmt_trims_trailing_zeros():
    assert fmt(10.0) == "10"
    assert fmt(0.1) == "0.1"
    assert fmt(-1.500) == "-1.5"
    assert fmt(0.0) == "0"
    assert fmt(124.5) == "124.5"


def test_encode_jog_is_relative_metric_and_carries_feed():
    assert encode_jog("X", 10.0, 1000.0) == "$J=G91 G21 X10 F1000"
    assert encode_jog("Y", -0.1, 500.0) == "$J=G91 G21 Y-0.1 F500"
    assert encode_jog("Z", 1.0, 200.0) == "$J=G91 G21 Z1 F200"


def test_encode_zero_sets_work_offset_for_named_axes():
    assert encode_zero("XY") == "G10 L20 P1 X0 Y0"
    assert encode_zero("Z") == "G10 L20 P1 Z0"
    assert encode_zero("XYZ") == "G10 L20 P1 X0 Y0 Z0"
