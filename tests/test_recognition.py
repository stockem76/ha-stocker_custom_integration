"""Unit tests for the HA-independent recognition logic."""

import importlib.util
import sys
from pathlib import Path

# Load the module by path so these tests run without Home Assistant installed
# (importing the package would execute __init__.py, which needs HA).
_PATH = Path(__file__).parents[1] / "custom_components/stocker_custom_integration/recognition.py"
_spec = importlib.util.spec_from_file_location("stocker_recognition", _PATH)
rec = importlib.util.module_from_spec(_spec)
sys.modules[_spec.name] = rec
_spec.loader.exec_module(rec)


class FakeClock:
    def __init__(self) -> None:
        self.now = 1000.0

    def __call__(self) -> float:
        return self.now


def make(clock: FakeClock | None = None):
    return rec.Recognizer(
        certain_threshold=0.9, likely_threshold=0.75, cooldown=120, clock=clock or FakeClock()
    )


def test_certain_face_announced_once_per_track():
    r = make()
    s = r.face("t1", "front_door", "Mark", 0.95, 1.0)
    assert s.kind == rec.KIND_PERSON and s.level == rec.LEVEL_CERTAIN
    assert rec.describe(s) == "Mark is at the front door."
    assert r.face("t1", "front_door", "Mark", 0.97, 2.0) is None


def test_low_score_waits_for_better_frame():
    r = make()
    assert r.face("t1", "front_door", "Mark", 0.6, 1.0) is None
    s = r.face("t1", "front_door", "Mark", 0.8, 2.0)
    assert s.level == rec.LEVEL_LIKELY
    assert rec.describe(s) == "I think Mark is at the front door."


def test_unknown_names_ignored():
    r = make()
    assert r.face("t1", "front_door", "unknown", 0.99, 1.0) is None
    assert r.face("t1", "front_door", None, 0.99, 1.0) is None
    assert not r.is_identified("t1")


def test_cooldown_suppresses_repeat_across_tracks_then_expires():
    clock = FakeClock()
    r = make(clock)
    assert r.face("t1", "front_door", "Mark", 0.95, 1.0)
    clock.now += 30
    assert r.face("t2", "drive", "Mark", 0.95, 2.0) is None
    clock.now += 200
    assert r.face("t3", "drive", "Mark", 0.95, 3.0)


def test_unknown_person_only_when_no_face_matched():
    r = make()
    r.track_started("t1", "front_door")
    r.track_started("t2", "front_door")
    r.face("t2", "front_door", "Sarah", 0.95, 1.0)
    s = r.unknown_person("t1", "front_door", 2.0)
    assert s.kind == rec.KIND_UNKNOWN_PERSON
    assert rec.describe(s) == "Someone I don't recognise is at the front door."
    assert r.unknown_person("t2", "front_door", 2.0) is None


def test_unknown_person_ignored_after_track_end():
    r = make()
    r.track_started("t1", "front_door")
    r.track_ended("t1")
    assert r.unknown_person("t1", "front_door", 2.0) is None


def test_known_plate_announced():
    r = make()
    s = r.plate("v1", "driveway", "Sarah's car", "AB12CDE", 0.92, 1.0)
    assert s.kind == rec.KIND_VEHICLE
    assert s.plate == "AB12CDE"
    assert rec.describe(s) == "Sarah's car has arrived at the driveway."


def test_unknown_plate_only_when_enabled():
    r = make()
    assert r.plate("v1", "driveway", None, "AB12CDE", 0.9, 1.0) is None
    s = r.plate("v2", "driveway", None, "AB12CDE", 0.9, 1.0, announce_unknown=True)
    assert s.kind == rec.KIND_UNKNOWN_VEHICLE and s.subject == "AB12CDE"
    assert "A B 1 2 C D E" in rec.describe(s)


def test_confidence_level_boundaries():
    assert rec.confidence_level(0.9, 0.9, 0.75) == rec.LEVEL_CERTAIN
    assert rec.confidence_level(0.75, 0.9, 0.75) == rec.LEVEL_LIKELY
    assert rec.confidence_level(0.74, 0.9, 0.75) == rec.LEVEL_POSSIBLE
