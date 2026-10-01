"""Config and options flow for the Stocker Custom Integration."""

from __future__ import annotations

from typing import Any

import voluptuous as vol
from homeassistant.config_entries import (
    ConfigEntry,
    ConfigFlow,
    ConfigFlowResult,
    OptionsFlow,
)
from homeassistant.core import callback
from homeassistant.helpers import selector

from .const import (
    CONF_ANNOUNCE_UNKNOWN_VEHICLES,
    CONF_CERTAIN_THRESHOLD,
    CONF_COOLDOWN,
    CONF_LIKELY_THRESHOLD,
    CONF_PRESENCE_MINUTES,
    CONF_TOPIC_PREFIX,
    CONF_UNKNOWN_CAMERAS,
    CONF_UNKNOWN_DELAY,
    DEFAULT_ANNOUNCE_UNKNOWN_VEHICLES,
    DEFAULT_CERTAIN_THRESHOLD,
    DEFAULT_COOLDOWN,
    DEFAULT_LIKELY_THRESHOLD,
    DEFAULT_NAME,
    DEFAULT_PRESENCE_MINUTES,
    DEFAULT_TOPIC_PREFIX,
    DEFAULT_UNKNOWN_CAMERAS,
    DEFAULT_UNKNOWN_DELAY,
    DOMAIN,
)


def _score() -> selector.NumberSelector:
    return selector.NumberSelector(
        selector.NumberSelectorConfig(min=0.5, max=1.0, step=0.01, mode="slider")
    )


def _seconds(maximum: int, unit: str = "s") -> selector.NumberSelector:
    return selector.NumberSelector(
        selector.NumberSelectorConfig(min=0, max=maximum, step=1, unit_of_measurement=unit)
    )


class StockerConfigFlow(ConfigFlow, domain=DOMAIN):
    """Handle a config flow."""

    VERSION = 1

    async def async_step_user(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        """Ask which MQTT topic prefix Frigate publishes on."""
        if user_input is not None:
            await self.async_set_unique_id(user_input[CONF_TOPIC_PREFIX])
            self._abort_if_unique_id_configured()
            return self.async_create_entry(title=DEFAULT_NAME, data=user_input)

        return self.async_show_form(
            step_id="user",
            data_schema=vol.Schema(
                {vol.Required(CONF_TOPIC_PREFIX, default=DEFAULT_TOPIC_PREFIX): str}
            ),
        )

    @staticmethod
    @callback
    def async_get_options_flow(config_entry: ConfigEntry) -> OptionsFlow:
        return StockerOptionsFlow()


class StockerOptionsFlow(OptionsFlow):
    """Tune thresholds and announcement behaviour."""

    async def async_step_init(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        errors: dict[str, str] = {}
        if user_input is not None:
            if user_input[CONF_LIKELY_THRESHOLD] > user_input[CONF_CERTAIN_THRESHOLD]:
                errors["base"] = "thresholds_order"
            else:
                return self.async_create_entry(data=user_input)

        opts = {**self.config_entry.options, **(user_input or {})}
        schema = vol.Schema(
            {
                vol.Required(
                    CONF_CERTAIN_THRESHOLD,
                    default=opts.get(CONF_CERTAIN_THRESHOLD, DEFAULT_CERTAIN_THRESHOLD),
                ): _score(),
                vol.Required(
                    CONF_LIKELY_THRESHOLD,
                    default=opts.get(CONF_LIKELY_THRESHOLD, DEFAULT_LIKELY_THRESHOLD),
                ): _score(),
                vol.Required(
                    CONF_COOLDOWN, default=opts.get(CONF_COOLDOWN, DEFAULT_COOLDOWN)
                ): _seconds(3600),
                vol.Required(
                    CONF_UNKNOWN_DELAY,
                    default=opts.get(CONF_UNKNOWN_DELAY, DEFAULT_UNKNOWN_DELAY),
                ): _seconds(60),
                vol.Optional(
                    CONF_UNKNOWN_CAMERAS,
                    default=opts.get(CONF_UNKNOWN_CAMERAS, DEFAULT_UNKNOWN_CAMERAS),
                ): str,
                vol.Required(
                    CONF_ANNOUNCE_UNKNOWN_VEHICLES,
                    default=opts.get(
                        CONF_ANNOUNCE_UNKNOWN_VEHICLES, DEFAULT_ANNOUNCE_UNKNOWN_VEHICLES
                    ),
                ): bool,
                vol.Required(
                    CONF_PRESENCE_MINUTES,
                    default=opts.get(CONF_PRESENCE_MINUTES, DEFAULT_PRESENCE_MINUTES),
                ): _seconds(240, "min"),
            }
        )
        return self.async_show_form(step_id="init", data_schema=schema, errors=errors)
