"""SMART Disk Monitor integration for Home Assistant."""
from __future__ import annotations

import logging

from homeassistant.config_entries import ConfigEntry
from homeassistant.const import Platform
from homeassistant.core import HomeAssistant

from .const import (
    DOMAIN,
    CONF_HOST,
    CONF_PORT,
    CONF_USERNAME,
    CONF_PASSWORD,
    CONF_SSH_KEY,
    CONF_SERVER_TYPE,
    CONF_SCAN_INTERVAL,
    DEFAULT_PORT,
    DEFAULT_SCAN_INTERVAL,
)
from .coordinator import SmartMonitorCoordinator
from .smart_fetcher import SmartDataFetcher

_LOGGER = logging.getLogger(__name__)

PLATFORMS: list[Platform] = [Platform.SENSOR, Platform.BINARY_SENSOR, Platform.BUTTON]


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Set up SMART Disk Monitor from a config entry."""
    _LOGGER.debug("smart_monitor: async_setup_entry called, platforms=%s", PLATFORMS)
    data = entry.data

    fetcher = SmartDataFetcher(
        host=data[CONF_HOST],
        port=data.get(CONF_PORT, DEFAULT_PORT),
        username=data[CONF_USERNAME],
        password=data.get(CONF_PASSWORD),
        ssh_key_path=data.get(CONF_SSH_KEY),
        server_type=data.get(CONF_SERVER_TYPE, "generic_linux"),
    )

    coordinator = SmartMonitorCoordinator(
        hass=hass,
        entry_id=entry.entry_id,
        fetcher=fetcher,
        server_name=data[CONF_HOST],
        scan_interval=data.get(CONF_SCAN_INTERVAL, DEFAULT_SCAN_INTERVAL),
    )

    await coordinator.async_config_entry_first_refresh()

    hass.data.setdefault(DOMAIN, {})[entry.entry_id] = coordinator

    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)

    return True


async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Unload a config entry."""
    unload_ok = await hass.config_entries.async_unload_platforms(entry, PLATFORMS)
    if unload_ok:
        hass.data[DOMAIN].pop(entry.entry_id)
    return unload_ok
