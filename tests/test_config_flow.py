"""Config flow tests (need pytest-homeassistant-custom-component)."""

import pytest

pytest.importorskip("pytest_homeassistant_custom_component")

from homeassistant import config_entries  # noqa: E402
from homeassistant.core import HomeAssistant  # noqa: E402
from homeassistant.data_entry_flow import FlowResultType  # noqa: E402

from custom_components.stocker_custom_integration.const import (  # noqa: E402
    CONF_TOPIC_PREFIX,
    DOMAIN,
)


async def test_user_flow_creates_entry(hass: HomeAssistant) -> None:
    result = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": config_entries.SOURCE_USER}
    )
    assert result["type"] is FlowResultType.FORM

    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], {CONF_TOPIC_PREFIX: "frigate"}
    )
    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert result["data"] == {CONF_TOPIC_PREFIX: "frigate"}


async def test_options_flow_validates_quiet_times(hass: HomeAssistant) -> None:
    from pytest_homeassistant_custom_component.common import MockConfigEntry

    entry = MockConfigEntry(domain=DOMAIN, data={CONF_TOPIC_PREFIX: "frigate"})
    entry.add_to_hass(hass)

    base = {
        "certain_threshold": 0.9,
        "likely_threshold": 0.75,
        "cooldown": 120,
        "unknown_delay": 6,
        "unknown_cameras": "",
        "announce_unknown_vehicles": False,
        "presence_minutes": 10,
    }

    result = await hass.config_entries.options.async_init(entry.entry_id)
    result = await hass.config_entries.options.async_configure(
        result["flow_id"], {**base, "quiet_times": "Garden=22-07"}
    )
    assert result["type"] is FlowResultType.FORM
    assert result["errors"] == {"quiet_times": "invalid_quiet_times"}

    result = await hass.config_entries.options.async_configure(
        result["flow_id"], {**base, "quiet_times": "Garden=22:00-07:00; doorbell=23:30-06:30"}
    )
    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert entry.options["quiet_times"] == "Garden=22:00-07:00; doorbell=23:30-06:30"
