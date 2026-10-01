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
    clock: Callable[[], float] = time.monotonic
    _tracks: dict[str, _Track] = field(default_factory=dict)
    _last_announced: dict[str, float] = field(default_factory=dict)

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
        if name and name.strip().lower() not in _IGNORED_NAMES:
            return self._named(KIND_VEHICLE, track_id, camera, name, score, timestamp, plate)
        if not plate or not announce_unknown:
            return None
        track = self._tracks.setdefault(track_id, _Track(camera=camera, is_vehicle=True))
        if track.announced or not self._cooldown_ok(f"plate:{plate.upper()}"):
            return None
        track.announced = True
        return Sighting(
            KIND_UNKNOWN_VEHICLE, None, score, LEVEL_UNKNOWN, camera, track_id, timestamp, plate
        )

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
