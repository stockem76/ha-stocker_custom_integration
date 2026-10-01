"""Data update coordinator for the Stocker Custom Integration."""

from __future__ import annotations

import logging
from typing import Any

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator

from .const import DEFAULT_SCAN_INTERVAL, DOMAIN

_LOGGER = logging.getLogger(__name__)


class StockerCoordinator(DataUpdateCoordinator[dict[str, Any]]):
    """Fetch data for the integration on a fixed interval."""

    def __init__(self, hass: HomeAssistant, entry: ConfigEntry) -> None:
        super().__init__(
            hass,
            _LOGGER,
            config_entry=entry,
            name=DOMAIN,
            update_interval=DEFAULT_SCAN_INTERVAL,
        )

    async def _async_update_data(self) -> dict[str, Any]:
        """Fetch the latest data.

        Replace with calls to the real data source and raise
        homeassistant.helpers.update_coordinator.UpdateFailed on errors.
        """
        return {"status": "ok"}
