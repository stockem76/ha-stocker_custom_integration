"""One "recently seen" binary sensor per known person or vehicle."""

from __future__ import annotations

from datetime import timedelta
from typing import Any

from homeassistant.components.binary_sensor import (
    BinarySensorDeviceClass,
    BinarySensorEntity,
)
from homeassistant.core import CALLBACK_TYPE, HomeAssistant, callback
from homeassistant.helpers.dispatcher import async_dispatcher_connect
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback
from homeassistant.helpers.event import async_call_later
from homeassistant.util import slugify

from . import StockerConfigEntry
from .const import (
    CONF_PRESENCE_MINUTES,
    DEFAULT_PRESENCE_MINUTES,
    SIGNAL_NEW_SUBJECT,
    SIGNAL_SIGHTING,
)
from .entity import StockerEntity
from .hub import StockerHub, signal
from .recognition import KIND_VEHICLE, Sighting


async def async_setup_entry(
    hass: HomeAssistant,
    entry: StockerConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    hub = entry.runtime_data
    async_add_entities(SeenRecentlySensor(hub, kind, name) for kind, name in hub.subjects)

    @callback
    def _new_subject(key: tuple[str, str]) -> None:
        async_add_entities([SeenRecentlySensor(hub, *key)])

    entry.async_on_unload(
        async_dispatcher_connect(hass, signal(SIGNAL_NEW_SUBJECT, entry.entry_id), _new_subject)
    )


class SeenRecentlySensor(StockerEntity, BinarySensorEntity):
    """On while a subject has been seen within the presence window."""

    _attr_device_class = BinarySensorDeviceClass.OCCUPANCY
    _attr_is_on = False

    def __init__(self, hub: StockerHub, kind: str, name: str) -> None:
        super().__init__(hub)
        self._kind, self._subject = kind, name
        self._attr_unique_id = f"{hub.entry.entry_id}_{kind}_{slugify(name)}"
        self._attr_translation_key = "vehicle_seen" if kind == KIND_VEHICLE else "person_seen"
        self._attr_translation_placeholders = {"name": name}
        opts = {**hub.entry.data, **hub.entry.options}
        self._window = timedelta(minutes=opts.get(CONF_PRESENCE_MINUTES, DEFAULT_PRESENCE_MINUTES))
        self._cancel_off: CALLBACK_TYPE | None = None
        self._attr_extra_state_attributes: dict[str, Any] = {}

    async def async_added_to_hass(self) -> None:
        self.async_on_remove(
            async_dispatcher_connect(
                self.hass, signal(SIGNAL_SIGHTING, self.hub.entry.entry_id), self._on_sighting
            )
        )
        self.async_on_remove(self._cancel_timer)

    @callback
    def _on_sighting(self, sighting: Sighting, _message: str) -> None:
        if sighting.kind != self._kind or sighting.name != self._subject:
            return
        self._cancel_timer()
        self._attr_is_on = True
        self._attr_extra_state_attributes = {
            "camera": sighting.camera,
            "confidence": sighting.confidence,
            "level": sighting.level,
        }
        self._cancel_off = async_call_later(self.hass, self._window, self._turn_off)
        self.async_write_ha_state()

    @callback
    def _turn_off(self, _now: Any) -> None:
        self._cancel_off = None
        self._attr_is_on = False
        self.async_write_ha_state()

    @callback
    def _cancel_timer(self) -> None:
        if self._cancel_off:
            self._cancel_off()
            self._cancel_off = None
