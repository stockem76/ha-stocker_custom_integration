"""Turn raw Frigate recognitions into announceable sightings.

This module deliberately has no Home Assistant imports so it can be unit tested
on its own. Frigate publishes many recognition updates per tracked object; the
Recognizer collapses them into at most one announcement per track, applies
confidence levels and per-subject cooldowns.
"""

from __future__ import annotations

import time
from collections.abc import Callable
from dataclasses import dataclass, field

KIND_PERSON = "person"
KIND_UNKNOWN_PERSON = "unknown_person"
KIND_VEHICLE = "vehicle"
KIND_UNKNOWN_VEHICLE = "unknown_vehicle"

LEVEL_CERTAIN = "certain"
LEVEL_LIKELY = "likely"
LEVEL_POSSIBLE = "possible"
LEVEL_UNKNOWN = "unknown"

_IGNORED_NAMES = {"", "unknown", "none"}


@dataclass(frozen=True)
class Sighting:
    """A single thing worth telling the household about."""

    kind: str
    name: str | None
    confidence: float | None
    level: str
    camera: str
    track_id: str
    timestamp: float
    plate: str | None = None

    @property
    def subject(self) -> str:
        """Human label for the sighting, used as a sensor state."""
        if self.name:
            return self.name
        if self.kind == KIND_UNKNOWN_VEHICLE and self.plate:
            return self.plate
        return "Unknown"


@dataclass
class _Track:
    camera: str
    best_name: str | None = None
    best_score: float = 0.0
    announced: bool = False
    is_vehicle: bool = False
    # Vehicles: announce only cars that arrive, not ones parked or leaving.
    first_box: tuple[float, float, float, float] | None = None
    arrived: bool | None = None  # None until movement or stationarity is seen
    pending: Sighting | None = None
    seen_keys: set[str] = field(default_factory=set)
    recently_present: bool = False  # vehicle was already around before this track


def _moved(a: tuple[float, ...], b: tuple[float, ...], fraction: float = 0.2) -> bool:
    """True if box b has shifted or resized noticeably relative to box a (x1, y1, x2, y2)."""
    aw, ah, bw, bh = a[2] - a[0], a[3] - a[1], b[2] - b[0], b[3] - b[1]
    size = max(aw, ah, 1.0)
    dx = (b[0] + b[2]) / 2 - (a[0] + a[2]) / 2
    dy = (b[1] + b[3]) / 2 - (a[1] + a[3]) / 2
    area_ratio = (bw * bh) / max(aw * ah, 1.0)
    return (dx * dx + dy * dy) ** 0.5 > fraction * size or not 0.7 <= area_ratio <= 1.43


def _vehicle_key(sighting: Sighting) -> str:
    if sighting.name:
        return f"{KIND_VEHICLE}:{sighting.name.lower()}"
    return f"plate:{(sighting.plate or '').upper()}"


def humanize_camera(camera: str) -> str:
    """front_door_cam -> 'front door cam'."""
    return camera.replace("_", " ").strip()


def spell_plate(plate: str) -> str:
    """Space out a plate so TTS reads it character by character."""
    return " ".join(ch for ch in plate.upper() if ch.isalnum())


def confidence_level(score: float, certain: float, likely: float) -> str:
    if score >= certain:
        return LEVEL_CERTAIN
    if score >= likely:
        return LEVEL_LIKELY
    return LEVEL_POSSIBLE


def describe(sighting: Sighting, camera_label: str | None = None) -> str:
    """Build the sentence Alexa should say."""
    where = camera_label or humanize_camera(sighting.camera)
    hedge = "I think " if sighting.level == LEVEL_LIKELY else ""
    if sighting.kind == KIND_PERSON:
        return f"{hedge}{sighting.name} is at the {where}."
    if sighting.kind == KIND_VEHICLE:
        return f"{hedge}{sighting.name} has arrived at the {where}."
    if sighting.kind == KIND_UNKNOWN_VEHICLE:
        plate = f", registration {spell_plate(sighting.plate)}" if sighting.plate else ""
        return f"An unrecognised vehicle{plate} is at the {where}."
    return f"Someone I don't recognise is at the {where}."


@dataclass
class Recognizer:
    """Stateful aggregator for one Frigate instance."""

    certain_threshold: float = 0.9
    likely_threshold: float = 0.75
    cooldown: float = 120.0
    vehicles_require_arrival: bool = True
    vehicle_absence: float = 1800.0  # a vehicle must be unseen this long to "arrive"
    clock: Callable[[], float] = time.monotonic
    wall_clock: Callable[[], float] = time.time
    _tracks: dict[str, _Track] = field(default_factory=dict)
    _last_announced: dict[str, float] = field(default_factory=dict)
    _vehicle_seen: dict[str, float] = field(default_factory=dict)

    def seen_vehicles(self) -> dict[str, float]:
        """Wall-clock last-seen time per vehicle, for persisting across restarts."""
        return dict(self._vehicle_seen)

    def load_seen_vehicles(self, seen: dict[str, float]) -> None:
        self._vehicle_seen.update({k: float(v) for k, v in seen.items()})

    def _note_vehicle(self, track: _Track, key: str) -> None:
        """Record a vehicle sighting; flag the track if the vehicle was already around.

        Frigate's tracker can hop between parked cars, which looks like movement, so
        a named vehicle seen within ``vehicle_absence`` before this track is treated
        as still present rather than arriving.
        """
        now = self.wall_clock()
        if key not in track.seen_keys:
            track.seen_keys.add(key)
            previous = self._vehicle_seen.get(key)
            if previous is not None and now - previous < self.vehicle_absence:
                track.recently_present = True
        self._vehicle_seen[key] = now

    def track_started(self, track_id: str, camera: str, *, vehicle: bool = False) -> None:
        self._tracks.setdefault(track_id, _Track(camera=camera, is_vehicle=vehicle))

    def track_ended(self, track_id: str) -> None:
        self._tracks.pop(track_id, None)

    def is_identified(self, track_id: str) -> bool:
        track = self._tracks.get(track_id)
        return bool(track and (track.announced or track.best_name))

    def face(
        self, track_id: str, camera: str, name: str | None, score: float, timestamp: float
    ) -> Sighting | None:
        return self._named(KIND_PERSON, track_id, camera, name, score, timestamp, None)

    def plate(
        self,
        track_id: str,
        camera: str,
        name: str | None,
        plate: str | None,
        score: float,
        timestamp: float,
        *,
        announce_unknown: bool = False,
    ) -> Sighting | None:
        track = self._tracks.setdefault(track_id, _Track(camera=camera, is_vehicle=True))
        if track.announced:
            return None
        if name and name.strip().lower() not in _IGNORED_NAMES:
            if score >= track.best_score:
                track.best_name, track.best_score = name.strip(), score
            level = confidence_level(
                track.best_score, self.certain_threshold, self.likely_threshold
            )
            if level == LEVEL_POSSIBLE:
                return None
            candidate = Sighting(
                KIND_VEHICLE,
                track.best_name,
                track.best_score,
                level,
                camera,
                track_id,
                timestamp,
                plate,
            )
        elif plate and announce_unknown and not track.best_name:
            candidate = Sighting(
                KIND_UNKNOWN_VEHICLE, None, score, LEVEL_UNKNOWN, camera, track_id, timestamp, plate
            )
        else:
            return None
        if self.vehicles_require_arrival:
            self._note_vehicle(track, _vehicle_key(candidate))
            if track.recently_present:
                track.announced, track.pending = True, None
                return None
        if not self.vehicles_require_arrival or track.arrived:
            return self._emit_vehicle(track, candidate)
        if track.arrived is None and (
            track.pending is None
            or candidate.kind == KIND_VEHICLE
            or track.pending.kind == KIND_UNKNOWN_VEHICLE
        ):
            track.pending = candidate  # wait until we see the vehicle move
        return None

    def vehicle_update(
        self,
        track_id: str,
        camera: str,
        box: list[float] | tuple[float, ...] | None,
        stationary: bool,
    ) -> Sighting | None:
        """Feed a vehicle's position; returns a held sighting once it is seen arriving.

        A vehicle counts as arriving if it moves before Frigate ever reports it
        stationary. Cars parked when Frigate starts, and cars that are parked and
        then drive away, are never announced.
        """
        track = self._tracks.setdefault(track_id, _Track(camera=camera, is_vehicle=True))
        now = self.wall_clock()
        for key in track.seen_keys:  # still in view: keep it "present"
            self._vehicle_seen[key] = now
        if track.arrived is not None:
            return None
        if box is not None and len(box) == 4:
            current = tuple(float(v) for v in box)
            if track.first_box is None:
                track.first_box = current
            elif _moved(track.first_box, current):
                track.arrived = True
        if track.arrived is None and stationary:
            track.arrived, track.pending = False, None
            return None
        if track.arrived and track.pending and not track.announced:
            return self._emit_vehicle(track, track.pending)
        return None

    def _emit_vehicle(self, track: _Track, sighting: Sighting) -> Sighting | None:
        track.announced, track.pending = True, None
        return sighting if self._cooldown_ok(_vehicle_key(sighting)) else None

    def unknown_person(self, track_id: str, camera: str, timestamp: float) -> Sighting | None:
        """Called when a person track has gone unidentified for the grace period."""
        track = self._tracks.get(track_id)
        if track is None or track.announced or track.best_name:
            return None
        if not self._cooldown_ok(f"unknown:{camera}"):
            return None
        track.announced = True
        return Sighting(KIND_UNKNOWN_PERSON, None, None, LEVEL_UNKNOWN, camera, track_id, timestamp)

    def _named(
        self,
        kind: str,
        track_id: str,
        camera: str,
        name: str | None,
        score: float,
        timestamp: float,
        plate: str | None,
    ) -> Sighting | None:
        if not name or name.strip().lower() in _IGNORED_NAMES:
            return None
        name = name.strip()
        track = self._tracks.setdefault(
            track_id, _Track(camera=camera, is_vehicle=kind == KIND_VEHICLE)
        )
        if score >= track.best_score:
            track.best_name, track.best_score = name, score
        level = confidence_level(track.best_score, self.certain_threshold, self.likely_threshold)
        if track.announced or level == LEVEL_POSSIBLE:
            return None
        if not self._cooldown_ok(f"{kind}:{track.best_name.lower()}"):
            track.announced = True  # seen recently: suppress for the rest of this track
            return None
        track.announced = True
        return Sighting(
            kind, track.best_name, track.best_score, level, camera, track_id, timestamp, plate
        )

    def _cooldown_ok(self, key: str) -> bool:
        now = self.clock()
        last = self._last_announced.get(key)
        if last is not None and now - last < self.cooldown:
            return False
        self._last_announced[key] = now
        return True
