"""The Stocker Custom Integration."""

from __future__ import annotations

from homeassistant.components import mqtt
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import Platform
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import ConfigEntryNotReady

from .hub import StockerHub

PLATFORMS: list[Platform] = [Platform.BINARY_SENSOR, Platform.SENSOR]

type StockerConfigEntry = ConfigEntry[StockerHub]


async def async_setup_entry(hass: HomeAssistant, entry: StockerConfigEntry) -> bool:
    """Set up the integration from a config entry."""
    if not await mqtt.async_wait_for_mqtt_client(hass):
        raise ConfigEntryNotReady("MQTT is not available")

    hub = StockerHub(hass, entry)
    await hub.async_start()
    entry.runtime_data = hub
    entry.async_on_unload(hub.async_stop)
    entry.async_on_unload(entry.add_update_listener(_async_reload))

    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    return True


async def async_unload_entry(hass: HomeAssistant, entry: StockerConfigEntry) -> bool:
    """Unload a config entry."""
    return await hass.config_entries.async_unload_platforms(entry, PLATFORMS)


async def _async_reload(hass: HomeAssistant, entry: StockerConfigEntry) -> None:
    await hass.config_entries.async_reload(entry.entry_id)
