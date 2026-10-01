"""Base entity for the Stocker Custom Integration."""

from __future__ import annotations

from homeassistant.helpers.device_registry import DeviceEntryType, DeviceInfo
from homeassistant.helpers.entity import Entity

from .const import DEFAULT_NAME, DOMAIN
from .hub import StockerHub


class StockerEntity(Entity):
    """Groups every entity under one service device."""

    _attr_has_entity_name = True
    _attr_should_poll = False

    def __init__(self, hub: StockerHub) -> None:
        self.hub = hub
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, hub.entry.entry_id)},
            name=DEFAULT_NAME,
            entry_type=DeviceEntryType.SERVICE,
        )
