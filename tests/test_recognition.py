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


def make(clock: FakeClock | None = None, require_arrival: bool = True):
    clock = clock or FakeClock()
    return rec.Recognizer(
        certain_threshold=0.9,
        likely_threshold=0.75,
        cooldown=120,
        vehicles_require_arrival=require_arrival,
        clock=clock,
        wall_clock=clock,
    )


PARKED = [100, 100, 300, 250]
APPROACHING = [140, 120, 380, 300]


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
    r = make(require_arrival=False)
    s = r.plate("v1", "driveway", "Sarah's car", "AB12CDE", 0.92, 1.0)
    assert s.kind == rec.KIND_VEHICLE
    assert s.plate == "AB12CDE"
    assert rec.describe(s) == "Sarah's car has arrived at the driveway."


def test_unknown_plate_only_when_enabled():
    r = make(require_arrival=False)
    assert r.plate("v1", "driveway", None, "AB12CDE", 0.9, 1.0) is None
    s = r.plate("v2", "driveway", None, "AB12CDE", 0.9, 1.0, announce_unknown=True)
    assert s.kind == rec.KIND_UNKNOWN_VEHICLE and s.subject == "AB12CDE"
    assert "A B 1 2 C D E" in rec.describe(s)


def test_confidence_level_boundaries():
    assert rec.confidence_level(0.9, 0.9, 0.75) == rec.LEVEL_CERTAIN
    assert rec.confidence_level(0.75, 0.9, 0.75) == rec.LEVEL_LIKELY
    assert rec.confidence_level(0.74, 0.9, 0.75) == rec.LEVEL_POSSIBLE


def test_parked_car_never_announced():
    """Frigate restarts and re-detects a car already on the drive."""
    r = make()
    assert r.vehicle_update("v1", "driveway", PARKED, stationary=False) is None
    assert r.plate("v1", "driveway", "Matt's A1", "RE61ZXB", 0.97, 1.0) is None
    assert r.vehicle_update("v1", "driveway", PARKED, stationary=True) is None
    assert r.vehicle_update("v1", "driveway", APPROACHING, stationary=False) is None


def test_arriving_car_announced_when_plate_read_after_movement():
    r = make()
    r.vehicle_update("v1", "driveway", PARKED, stationary=False)
    assert r.vehicle_update("v1", "driveway", APPROACHING, stationary=False) is None
    s = r.plate("v1", "driveway", "Ben's Yaris", "LM62NJG", 0.92, 2.0)
    assert s.kind == rec.KIND_VEHICLE and s.name == "Ben's Yaris"


def test_arriving_car_announced_when_plate_read_before_movement():
    r = make()
    r.vehicle_update("v1", "driveway", PARKED, stationary=False)
    assert r.plate("v1", "driveway", "Ben's Yaris", "LM62NJG", 0.92, 1.0) is None
    s = r.vehicle_update("v1", "driveway", APPROACHING, stationary=True)
    assert s is not None and s.name == "Ben's Yaris"
    assert r.vehicle_update("v1", "driveway", PARKED, stationary=False) is None


def test_small_jitter_is_not_movement():
    r = make()
    r.vehicle_update("v1", "driveway", PARKED, stationary=False)
    r.plate("v1", "driveway", "Matt's A1", "RE61ZXB", 0.97, 1.0)
    assert r.vehicle_update("v1", "driveway", [104, 102, 305, 252], stationary=False) is None
    assert r.vehicle_update("v1", "driveway", [104, 102, 305, 252], stationary=True) is None


def test_named_plate_beats_unknown_plate_while_pending():
    r = make()
    r.vehicle_update("v1", "driveway", PARKED, stationary=False)
    r.plate("v1", "driveway", "Ben's Yaris", "LM62NJG", 0.92, 1.0)
    r.plate("v1", "driveway", None, "LM62NJG", 0.95, 1.5, announce_unknown=True)
    s = r.vehicle_update("v1", "driveway", APPROACHING, stationary=False)
    assert s.kind == rec.KIND_VEHICLE and s.name == "Ben's Yaris"


def test_moved_detects_shift_and_resize():
    assert rec._moved((0, 0, 100, 100), (30, 0, 130, 100))
    assert rec._moved((0, 0, 100, 100), (0, 0, 130, 130))
    assert not rec._moved((0, 0, 100, 100), (5, 5, 105, 105))


ELSEWHERE = [300, 120, 520, 260]  # another parked car the tracker can hop to


def arrive(r, track, name="Ben's Yaris", plate="LM62NJG", score=0.92, t=1.0):
    r.vehicle_update(track, "doorbell", PARKED, stationary=False)
    r.plate(track, "doorbell", name, plate, score, t)
    return r.vehicle_update(track, "doorbell", APPROACHING, stationary=False)


def test_tracker_hopping_between_parked_cars_is_not_an_arrival():
    """Tonight's case: a parked car re-detected minutes later with a jumpy track."""
    clock = FakeClock()
    r = make(clock)
    assert arrive(r, "v1") is not None  # genuinely arrived earlier
    r.track_ended("v1")
    clock.now += 300  # re-detected 5 minutes later, tracker hops to another car
    r.vehicle_update("v2", "doorbell", PARKED, stationary=False)
    assert r.plate("v2", "doorbell", "Ben's Yaris", "LM62NJG", 0.90, 2.0) is None
    assert r.vehicle_update("v2", "doorbell", ELSEWHERE, stationary=False) is None


def test_vehicle_returning_after_absence_is_announced():
    clock = FakeClock()
    r = make(clock)
    assert arrive(r, "v1") is not None
    r.track_ended("v1")
    clock.now += 3600  # away for an hour
    assert arrive(r, "v2", t=3.0) is not None


def test_vehicle_still_in_view_stays_present():
    clock = FakeClock()
    r = make(clock)
    arrive(r, "v1")
    for _ in range(4):  # parked and tracked for 40 minutes
        clock.now += 600
        r.vehicle_update("v1", "doorbell", APPROACHING, stationary=True)
    r.track_ended("v1")
    clock.now += 120
    assert arrive(r, "v2", t=5.0) is None


def test_seen_vehicles_round_trip():
    clock = FakeClock()
    r = make(clock)
    arrive(r, "v1")
    r2 = make(clock)
    r2.load_seen_vehicles(r.seen_vehicles())
    clock.now += 60
    assert arrive(r2, "v9") is None  # restart does not forget a parked car
