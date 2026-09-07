from __future__ import annotations

from grbl.ports import BAUD_RATES, PortInfo, autoselect, identify


def make(device: str, likely: bool) -> PortInfo:
    return PortInfo(device, "test", None, None, likely, None)


def test_identifies_ch340():
    likely, chip = identify(0x1A86, 0x7523)
    assert likely is True
    assert chip == "CH340"


def test_identifies_cp2102():
    likely, chip = identify(0x10C4, 0xEA60)
    assert likely is True
    assert chip == "CP2102"


def test_identifies_official_arduino():
    likely, chip = identify(0x2341, 0x0043)
    assert likely is True
    assert chip == "Arduino"


def test_identifies_esp32_usb_bridge():
    likely, _chip = identify(0x303A, 0x1001)
    assert likely is True


def test_unknown_vid_is_not_flagged():
    likely, chip = identify(0x9999, 0x0001)
    assert likely is False
    assert chip is None


def test_missing_vid_is_not_flagged():
    likely, chip = identify(None, None)
    assert likely is False
    assert chip is None


def test_autoselect_picks_the_only_likely_controller():
    ports = [make("COM1", False), make("COM5", True), make("COM9", False)]
    assert autoselect(ports) == "COM5"


def test_autoselect_declines_when_ambiguous():
    ports = [make("COM5", True), make("COM6", True)]
    assert autoselect(ports) is None


def test_autoselect_declines_when_nothing_looks_right():
    assert autoselect([make("COM1", False)]) is None


def test_autoselect_handles_an_empty_list():
    assert autoselect([]) is None


def test_baud_rates_include_the_grbl_defaults():
    assert 115200 in BAUD_RATES
    assert 250000 in BAUD_RATES
    assert BAUD_RATES[0] == 115200  # the default goes first
