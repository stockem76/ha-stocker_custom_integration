"""Bridge between Frigate's MQTT output and Home Assistant."""

from __future__ import annotations

import logging
import time
from dataclasses import asdict
from functools import partial
from typing import Any

from homeassistant.components import mqtt
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import CALLBACK_TYPE, HomeAssistant, callback
from homeassistant.helpers.dispatcher import async_dispatcher_send
from homeassistant.helpers.event import async_call_later
from homeassistant.helpers.storage import Store
from homeassistant.util.json import json_loads

from .const import (
    CONF_ANNOUNCE_UNKNOWN_VEHICLES,
    CONF_CERTAIN_THRESHOLD,
    CONF_COOLDOWN,
    CONF_LIKELY_THRESHOLD,
    CONF_TOPIC_PREFIX,
    CONF_UNKNOWN_CAMERAS,
    CONF_UNKNOWN_DELAY,
    DEFAULT_ANNOUNCE_UNKNOWN_VEHICLES,
    DEFAULT_CERTAIN_THRESHOLD,
    DEFAULT_COOLDOWN,
    DEFAULT_LIKELY_THRESHOLD,
    DEFAULT_TOPIC_PREFIX,
    DEFAULT_UNKNOWN_CAMERAS,
    DEFAULT_UNKNOWN_DELAY,
    EVENT_VEHICLE,
    EVENT_VISITOR,
    SIGNAL_NEW_SUBJECT,
    SIGNAL_SIGHTING,
    STORAGE_KEY,
    STORAGE_VERSION,
)
from .recognition import (
    KIND_PERSON,
    KIND_UNKNOWN_VEHICLE,
    KIND_VEHICLE,
    Recognizer,
    Sighting,
    describe,
)

_LOGGER = logging.getLogger(__name__)

VEHICLE_LABELS = {"car", "motorcycle", "truck", "bus"}


def signal(base: str, entry_id: str) -> str:
    return f"{base}_{entry_id}"


class StockerHub:
    """Subscribes to Frigate, runs the Recognizer and publishes sightings."""

    def __init__(self, hass: HomeAssistant, entry: ConfigEntry) -> None:
        self.hass = hass
        self.entry = entry
        opts = {**entry.data, **entry.options}
        self._prefix: str = opts.get(CONF_TOPIC_PREFIX, DEFAULT_TOPIC_PREFIX).rstrip("/")
        self._unknown_delay: float = opts.get(CONF_UNKNOWN_DELAY, DEFAULT_UNKNOWN_DELAY)
        self._announce_unknown_vehicles: bool = opts.get(
            CONF_ANNOUNCE_UNKNOWN_VEHICLES, DEFAULT_ANNOUNCE_UNKNOWN_VEHICLES
        )
        cameras = opts.get(CONF_UNKNOWN_CAMERAS, DEFAULT_UNKNOWN_CAMERAS)
        self._unknown_cameras = {c.strip() for c in cameras.split(",") if c.strip()}
        self.recognizer = Recognizer(
            certain_threshold=opts.get(CONF_CERTAIN_THRESHOLD, DEFAULT_CERTAIN_THRESHOLD),
            likely_threshold=opts.get(CONF_LIKELY_THRESHOLD, DEFAULT_LIKELY_THRESHOLD),
            cooldown=opts.get(CONF_COOLDOWN, DEFAULT_COOLDOWN),
        )
        self.subjects: set[tuple[str, str]] = set()
        self.last_visitor: Sighting | None = None
        self.last_vehicle: Sighting | None = None
        self._store: Store[dict[str, Any]] = Store(
            hass, STORAGE_VERSION, f"{STORAGE_KEY}.{entry.entry_id}"
        )
        self._unknown_timers: dict[str, CALLBACK_TYPE] = {}
        self._unsubs: list[CALLBACK_TYPE] = []

    async def async_start(self) -> None:
        data = await self._store.async_load() or {}
        self.subjects = {(s["kind"], s["name"]) for s in data.get("subjects", [])}
        self._unsubs.append(
            await mqtt.async_subscribe(
                self.hass, f"{self._prefix}/tracked_object_update", self._on_object_update
            )
        )
        self._unsubs.append(
            await mqtt.async_subscribe(self.hass, f"{self._prefix}/events", self._on_event)
        )

    @callback
    def async_stop(self) -> None:
        for unsub in self._unsubs:
            unsub()
        self._unsubs.clear()
        for cancel in self._unknown_timers.values():
            cancel()
        self._unknown_timers.clear()

    @staticmethod
    def _parse(msg: mqtt.ReceiveMessage) -> dict[str, Any] | None:
        try:
            payload = json_loads(msg.payload)
        except ValueError:
            _LOGGER.debug("Ignoring non-JSON payload on %s", msg.topic)
            return None
        return payload if isinstance(payload, dict) else None

    @callback
    def _on_object_update(self, msg: mqtt.ReceiveMessage) -> None:
        """Handle frigate/tracked_object_update (face and lpr results)."""
        payload = self._parse(msg)
        if not payload:
            return
        track_id, camera = payload.get("id"), payload.get("camera")
        if not track_id or not camera:
            return
        score = float(payload.get("score") or 0.0)
        ts = payload.get("timestamp") or time.time()
        if payload.get("type") == "face":
            sighting = self.recognizer.face(track_id, camera, payload.get("name"), score, ts)
            if self.recognizer.is_identified(track_id):
                self._cancel_unknown(track_id)
            self._publish(sighting)
        elif payload.get("type") == "lpr":
            self._publish(
                self.recognizer.plate(
                    track_id,
                    camera,
                    payload.get("name"),
                    payload.get("plate"),
                    score,
                    ts,
                    announce_unknown=self._announce_unknown_vehicles,
                )
            )

    @callback
    def _on_event(self, msg: mqtt.ReceiveMessage) -> None:
        """Handle frigate/events (track lifecycle plus sub_label fallbacks)."""
        payload = self._parse(msg)
        if not payload:
            return
        after = payload.get("after") or {}
        track_id, camera, label = after.get("id"), after.get("camera"), after.get("label")
        if not track_id or not camera:
            return
        if payload.get("type") == "end":
            self._cancel_unknown(track_id)
            self.recognizer.track_ended(track_id)
            return
        if after.get("false_positive"):
            return

        ts = after.get("frame_time") or time.time()
        sub_name, sub_score = _sub_label(after.get("sub_label"))

        if label == "person":
            self.recognizer.track_started(track_id, camera)
            if sub_name:
                self._publish(self.recognizer.face(track_id, camera, sub_name, sub_score, ts))
            if self.recognizer.is_identified(track_id):
                self._cancel_unknown(track_id)
            elif payload.get("type") == "new" and self._watch_unknowns(camera):
                self._unknown_timers[track_id] = async_call_later(
                    self.hass, self._unknown_delay, partial(self._unknown_due, track_id, camera)
                )
        elif label in VEHICLE_LABELS:
            self.recognizer.track_started(track_id, camera, vehicle=True)
            plate = after.get("recognized_license_plate")
            if sub_name or plate:
                score = after.get("recognized_license_plate_score") or sub_score
                self._publish(
                    self.recognizer.plate(
                        track_id,
                        camera,
                        sub_name,
                        plate,
                        float(score or 0.0),
                        ts,
                        announce_unknown=self._announce_unknown_vehicles,
                    )
                )

    def _watch_unknowns(self, camera: str) -> bool:
        return not self._unknown_cameras or camera in self._unknown_cameras

    @callback
    def _unknown_due(self, track_id: str, camera: str, _now: Any) -> None:
        self._unknown_timers.pop(track_id, None)
        self._publish(self.recognizer.unknown_person(track_id, camera, time.time()))

    @callback
    def _cancel_unknown(self, track_id: str) -> None:
        if cancel := self._unknown_timers.pop(track_id, None):
            cancel()

    @callback
    def _publish(self, sighting: Sighting | None) -> None:
        if sighting is None:
            return
        message = describe(sighting)
        is_vehicle = sighting.kind in (KIND_VEHICLE, KIND_UNKNOWN_VEHICLE)
        if is_vehicle:
            self.last_vehicle = sighting
        else:
            self.last_visitor = sighting

        if sighting.kind in (KIND_PERSON, KIND_VEHICLE) and sighting.name:
            key = (sighting.kind, sighting.name)
            if key not in self.subjects:
                self.subjects.add(key)
                self._store.async_delay_save(self._data_to_save, 1)
                async_dispatcher_send(
                    self.hass, signal(SIGNAL_NEW_SUBJECT, self.entry.entry_id), key
                )

        async_dispatcher_send(
            self.hass, signal(SIGNAL_SIGHTING, self.entry.entry_id), sighting, message
        )
        self.hass.bus.async_fire(
            EVENT_VEHICLE if is_vehicle else EVENT_VISITOR,
            {**asdict(sighting), "message": message, "subject": sighting.subject},
        )

    def _data_to_save(self) -> dict[str, Any]:
        return {
            "subjects": [{"kind": k, "name": n} for k, n in sorted(self.subjects)],
        }


def _sub_label(value: Any) -> tuple[str | None, float]:
    """Frigate sends sub_label as [name, score], a bare string, or null."""
    if isinstance(value, list | tuple) and value:
        name = value[0] if isinstance(value[0], str) else None
        score = float(value[1]) if len(value) > 1 and value[1] is not None else 0.0
        return name, score
    if isinstance(value, str):
        return value, 1.0  # a bare string is a manually assigned label
    return None, 0.0
