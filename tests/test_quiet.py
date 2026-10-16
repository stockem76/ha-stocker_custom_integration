"""Unit tests for per-camera quiet times."""

import importlib.util
import sys
from datetime import time
from pathlib import Path

import pytest

_PATH = Path(__file__).parents[1] / "custom_components/stocker_custom_integration/quiet.py"
_spec = importlib.util.spec_from_file_location("stocker_quiet", _PATH)
quiet = importlib.util.module_from_spec(_spec)
sys.modules[_spec.name] = quiet
_spec.loader.exec_module(quiet)


def test_empty_means_never_quiet():
    q = quiet.parse_quiet_times("")
    assert q == {}
    assert not quiet.is_quiet(q, "Garden", time(3, 0))


def test_overnight_window_for_one_camera():
    q = quiet.parse_quiet_times("Garden=22:00-07:00")
    assert quiet.is_quiet(q, "Garden", time(23, 30))
    assert quiet.is_quiet(q, "Garden", time(6, 59))
    assert not quiet.is_quiet(q, "Garden", time(7, 0))
    assert not quiet.is_quiet(q, "doorbell", time(23, 30))


def test_camera_names_are_case_insensitive():
    q = quiet.parse_quiet_times("garden=22:00-07:00")
    assert quiet.is_quiet(q, "Garden", time(1, 0))


def test_several_cameras_and_windows():
    q = quiet.parse_quiet_times("Garden=12:00-13:00, 22:00-07:00; doorbell=23:30-06:30")
    assert quiet.is_quiet(q, "Garden", time(12, 30))
    assert not quiet.is_quiet(q, "Garden", time(14, 0))
    assert quiet.is_quiet(q, "doorbell", time(0, 15))
    assert not quiet.is_quiet(q, "doorbell", time(23, 0))


def test_star_applies_to_every_camera():
    q = quiet.parse_quiet_times("*=01:00-05:00")
    assert quiet.is_quiet(q, "hall", time(2, 0))
    assert not quiet.is_quiet(q, "hall", time(6, 0))


def test_same_day_window_end_is_exclusive():
    q = quiet.parse_quiet_times("doorbell=09:00-17:00")
    assert quiet.is_quiet(q, "doorbell", time(9, 0))
    assert not quiet.is_quiet(q, "doorbell", time(17, 0))


@pytest.mark.parametrize(
    "text",
    ["Garden", "Garden=22-07", "Garden=25:00-07:00", "=22:00-07:00", "Garden=22:00-22:00"],
)
def test_invalid_entries_raise(text):
    with pytest.raises(ValueError):
        quiet.parse_quiet_times(text)
