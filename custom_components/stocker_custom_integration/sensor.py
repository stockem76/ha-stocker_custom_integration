"""Sensor platform for the Stocker Custom Integration."""

from __future__ import annotations

from homeassistant.components.sensor import SensorEntity
from homeassistant.core import HomeAssistant
from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from . import StockerConfigEntry
from .const import DOMAIN
from .coordinator import StockerCoordinator


async def async_setup_entry(
    hass: HomeAssistant,
    entry: StockerConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    """Set up sensors from a config entry."""
    async_add_entities([StockerStatusSensor(entry.runtime_data)])


class StockerStatusSensor(CoordinatorEntity[StockerCoordinator], SensorEntity):
    """Example sensor exposing the coordinator status."""

    _attr_has_entity_name = True
    _attr_translation_key = "status"

    def __init__(self, coordinator: StockerCoordinator) -> None:
        super().__init__(coordinator)
        entry = coordinator.config_entry
        self._attr_unique_id = f"{entry.entry_id}_status"
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, entry.entry_id)},
            name=entry.title,
        )

    @property
    def native_value(self) -> str | None:
        return self.coordinator.data.get("status")
