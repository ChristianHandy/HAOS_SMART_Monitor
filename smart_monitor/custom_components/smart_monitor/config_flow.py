"""Config flow for SMART Disk Monitor."""
from __future__ import annotations

import logging
from typing import Any

import voluptuous as vol
from homeassistant import config_entries
from homeassistant.core import HomeAssistant, callback
from homeassistant.data_entry_flow import FlowResult

from .const import (
    DOMAIN,
    CONF_HOST,
    CONF_PORT,
    CONF_USERNAME,
    CONF_PASSWORD,
    CONF_SSH_KEY,
    CONF_SERVER_TYPE,
    CONF_SCAN_INTERVAL,
    SERVER_TYPES,
    DEFAULT_PORT,
    DEFAULT_SCAN_INTERVAL,
)
from .smart_fetcher import SmartDataFetcher

_LOGGER = logging.getLogger(__name__)

STEP_USER_SCHEMA = vol.Schema(
    {
        vol.Required(CONF_HOST): str,
        vol.Optional(CONF_PORT, default=DEFAULT_PORT): int,
        vol.Required(CONF_USERNAME): str,
        vol.Optional(CONF_PASSWORD): str,
        vol.Optional(CONF_SSH_KEY): str,
        vol.Optional(CONF_SERVER_TYPE, default="generic_linux"): vol.In(SERVER_TYPES),
        vol.Optional(CONF_SCAN_INTERVAL, default=DEFAULT_SCAN_INTERVAL): int,
    }
)


async def _test_connection(hass: HomeAssistant, data: dict[str, Any]) -> None:
    """Try to connect and list disks; raise on failure."""
    fetcher = SmartDataFetcher(
        host=data[CONF_HOST],
        port=data[CONF_PORT],
        username=data[CONF_USERNAME],
        password=data.get(CONF_PASSWORD),
        ssh_key_path=data.get(CONF_SSH_KEY),
        server_type=data.get(CONF_SERVER_TYPE, "generic_linux"),
    )
    await hass.async_add_executor_job(fetcher.connect)
    await hass.async_add_executor_job(fetcher.disconnect)


class SmartMonitorConfigFlow(config_entries.ConfigFlow, domain=DOMAIN):
    """Handle a config flow for SMART Disk Monitor."""

    VERSION = 1

    async def async_step_user(
        self, user_input: dict[str, Any] | None = None
    ) -> FlowResult:
        errors: dict[str, str] = {}

        if user_input is not None:
            try:
                await _test_connection(self.hass, user_input)
            except Exception as exc:  # noqa: BLE001
                _LOGGER.error("Connection test failed: %s", exc)
                errors["base"] = "cannot_connect"
            else:
                title = f"{user_input[CONF_SERVER_TYPE].capitalize()} – {user_input[CONF_HOST]}"
                return self.async_create_entry(title=title, data=user_input)

        return self.async_show_form(
            step_id="user",
            data_schema=STEP_USER_SCHEMA,
            errors=errors,
            description_placeholders={
                "server_types": ", ".join(SERVER_TYPES),
            },
        )

    @staticmethod
    @callback
    def async_get_options_flow(config_entry: config_entries.ConfigEntry) -> SmartMonitorOptionsFlow:
        return SmartMonitorOptionsFlow(config_entry)


class SmartMonitorOptionsFlow(config_entries.OptionsFlow):
    """Allow updating scan interval and credentials without re-adding."""

    def __init__(self, config_entry: config_entries.ConfigEntry) -> None:
        self.config_entry = config_entry

    async def async_step_init(
        self, user_input: dict[str, Any] | None = None
    ) -> FlowResult:
        if user_input is not None:
            return self.async_create_entry(title="", data=user_input)

        current = self.config_entry.data
        schema = vol.Schema(
            {
                vol.Optional(
                    CONF_SCAN_INTERVAL,
                    default=current.get(CONF_SCAN_INTERVAL, DEFAULT_SCAN_INTERVAL),
                ): int,
                vol.Optional(CONF_PASSWORD, default=current.get(CONF_PASSWORD, "")): str,
                vol.Optional(CONF_SSH_KEY, default=current.get(CONF_SSH_KEY, "")): str,
            }
        )
        return self.async_show_form(step_id="init", data_schema=schema)
