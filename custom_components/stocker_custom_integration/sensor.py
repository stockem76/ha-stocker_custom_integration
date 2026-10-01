"""Last visitor / last vehicle sensors."""

from __future__ import annotations

from dataclasses import asdict
from typing import Any

from homeassistant.components.sensor import SensorEntity
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.dispatcher import async_dispatcher_connect
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback
from homeassistant.helpers.restore_state import RestoreEntity

from . import StockerConfigEntry
from .const import SIGNAL_SIGHTING
from .entity import StockerEntity
from .hub import StockerHub, signal
from .recognition import KIND_UNKNOWN_VEHICLE, KIND_VEHICLE, Sighting

_ATTRS = ("kind", "name", "confidence", "level", "camera", "track_id", "plate", "message")


async def async_setup_entry(
    hass: HomeAssistant,
    entry: StockerConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    hub = entry.runtime_data
    async_add_entities(
        [
            LastSightingSensor(hub, "last_visitor", vehicles=False),
            LastSightingSensor(hub, "last_vehicle", vehicles=True),
        ]
    )


class LastSightingSensor(StockerEntity, RestoreEntity, SensorEntity):
    """Shows the most recent announced visitor or vehicle."""

    def __init__(self, hub: StockerHub, key: str, *, vehicles: bool) -> None:
        super().__init__(hub)
        self._vehicles = vehicles
        self._attr_translation_key = key
        self._attr_unique_id = f"{hub.entry.entry_id}_{key}"
        self._attr_extra_state_attributes: dict[str, Any] = {}

    async def async_added_to_hass(self) -> None:
        await super().async_added_to_hass()
        if (last := await self.async_get_last_state()) is not None:
            self._attr_native_value = last.state
            self._attr_extra_state_attributes = {
                k: v for k, v in last.attributes.items() if k in _ATTRS
            }
        self.async_on_remove(
            async_dispatcher_connect(
                self.hass, signal(SIGNAL_SIGHTING, self.hub.entry.entry_id), self._on_sighting
            )
        )

    @callback
    def _on_sighting(self, sighting: Sighting, message: str) -> None:
        is_vehicle = sighting.kind in (KIND_VEHICLE, KIND_UNKNOWN_VEHICLE)
        if is_vehicle != self._vehicles:
            return
        self._attr_native_value = sighting.subject
        data = asdict(sighting)
        self._attr_extra_state_attributes = {
            **{k: data[k] for k in _ATTRS if k in data},
            "message": message,
        }
        self.async_write_ha_state()
