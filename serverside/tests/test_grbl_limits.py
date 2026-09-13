from __future__ import annotations

import pytest

from grbl.limits import LimitError, check_jog
from grbl.profile import Profile


@pytest.fixture()
def profile():
    return Profile(travel_x=300.0, travel_y=200.0, travel_z=5.0)


def test_allows_a_jog_inside_the_envelope(profile):
    check_jog(profile, (100.0, 100.0, 2.0), "X", 10.0)


def test_allows_landing_exactly_on_the_limit(profile):
    check_jog(profile, (290.0, 0.0, 0.0), "X", 10.0)


def test_refuses_a_jog_past_the_far_limit(profile):
    with pytest.raises(LimitError) as exc:
        check_jog(profile, (295.0, 0.0, 0.0), "X", 10.0)
    assert "305" in str(exc.value)
    assert "300" in str(exc.value)


def test_refuses_a_jog_below_zero(profile):
    with pytest.raises(LimitError) as exc:
        check_jog(profile, (5.0, 0.0, 0.0), "X", -10.0)
    assert "-5" in str(exc.value)


def test_checks_the_y_axis(profile):
    with pytest.raises(LimitError):
        check_jog(profile, (0.0, 195.0, 0.0), "Y", 10.0)


def test_checks_the_z_axis(profile):
    with pytest.raises(LimitError):
        check_jog(profile, (0.0, 0.0, 4.0), "Z", 2.0)


def test_message_names_the_axis(profile):
    with pytest.raises(LimitError) as exc:
        check_jog(profile, (0.0, 195.0, 0.0), "Y", 10.0)
    assert "Y" in str(exc.value)


def test_rejects_an_unknown_axis(profile):
    with pytest.raises(LimitError, match="unknown axis"):
        check_jog(profile, (0.0, 0.0, 0.0), "A", 1.0)


def test_axis_letter_is_case_insensitive(profile):
    check_jog(profile, (0.0, 0.0, 0.0), "x", 1.0)


def test_default_profile_has_a_real_envelope():
    """A zero-travel default would refuse every jog with a confusing message."""
    from grbl.profile import DEFAULT_PROFILE

    assert DEFAULT_PROFILE.travel_x > 0
    assert DEFAULT_PROFILE.travel_y > 0
    assert DEFAULT_PROFILE.travel_z > 0
    assert DEFAULT_PROFILE.rx_buffer == 128
    assert DEFAULT_PROFILE.baud == 115200


def test_z_may_jog_below_zero_to_drop_the_pen(profile):
    # grbl_servo_z drops the pen only when machine Z < 0, and the board
    # powers up at Z0. A floor at 0 would make pen-down unreachable by jog.
    check_jog(profile, (0.0, 0.0, 0.0), "Z", -1.0)


def test_z_still_has_a_floor(profile):
    with pytest.raises(LimitError):
        check_jog(profile, (0.0, 0.0, 0.0), "Z", -10.0)


# --- the pen starts at the TOP-left: Y is 0 at the top and runs negative ----
from grbl.limits import check_program  # noqa: E402


def test_y_jogs_down_from_the_top(profile):
    check_jog(profile, (0.0, 0.0, 0.0), "Y", -50.0)


def test_y_cannot_jog_above_the_top(profile):
    with pytest.raises(LimitError) as exc:
        check_jog(profile, (0.0, 0.0, 0.0), "Y", 5.0)
    assert "Y" in str(exc.value)


def test_y_cannot_jog_past_the_bottom(profile):
    with pytest.raises(LimitError):
        check_jog(profile, (0.0, -195.0, 0.0), "Y", -10.0)


def test_a_top_left_program_fits(profile):
    check_program(profile, ["G21", "G90", "G0 X0 Y0", "G1 X50 Y-40", "G0 X0 Y0"])


def test_a_program_above_the_top_edge_is_refused(profile):
    with pytest.raises(LimitError) as exc:
        check_program(profile, ["G21", "G90", "G0 X10 Y30"])
    assert "Y30" in str(exc.value)


def test_a_program_below_the_bottom_edge_is_refused(profile):
    with pytest.raises(LimitError):
        check_program(profile, ["G21", "G90", "G0 X10 Y-250"])
