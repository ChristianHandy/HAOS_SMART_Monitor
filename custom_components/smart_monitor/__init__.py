"""The SMART Disk Monitor integration."""

from collections.abc import Mapping
from typing import Any

from aiosmartctl import SmartctlClient

from homeassistant.const import (
    CONF_HOST,
    CONF_PASSWORD,
    CONF_PORT,
    CONF_USERNAME,
    Platform,
)
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import ConfigEntryAuthFailed
from homeassistant.helpers import device_registry as dr

from .const import CONF_HOST_KEY, CONF_PRIVATE_KEY, CONF_USE_SUDO, DOMAIN
from .coordinator import SmartMonitorConfigEntry, SmartMonitorCoordinator

PLATFORMS: list[Platform] = [Platform.BINARY_SENSOR, Platform.BUTTON, Platform.SENSOR]


def create_client(data: Mapping[str, Any]) -> SmartctlClient:
    """Create a smartctl client from config entry data."""
    return SmartctlClient(
        data[CONF_HOST],
        port=data[CONF_PORT],
        username=data[CONF_USERNAME],
        password=data.get(CONF_PASSWORD) or None,
        private_key=data.get(CONF_PRIVATE_KEY) or None,
        known_host_key=data.get(CONF_HOST_KEY) or None,
        use_sudo=data.get(CONF_USE_SUDO, False),
    )


async def async_setup_entry(
    hass: HomeAssistant, entry: SmartMonitorConfigEntry
) -> bool:
    """Set up SMART Disk Monitor from a config entry."""
    if not entry.data.get(CONF_HOST_KEY):
        # Entries made before host keys were pinned need the user to confirm one.
        raise ConfigEntryAuthFailed(
            translation_domain=DOMAIN, translation_key="host_key_missing"
        )

    coordinator = SmartMonitorCoordinator(hass, entry, create_client(entry.data))
    await coordinator.async_config_entry_first_refresh()

    host = coordinator.host_info
    coordinator.host_device_id = (
        dr.async_get(hass)
        .async_get_or_create(
            config_entry_id=entry.entry_id,
            identifiers={(DOMAIN, str(entry.unique_id))},
            name=host.hostname or entry.data[CONF_HOST],
            model=host.os_name,
            sw_version=host.os_version,
        )
        .id
    )

    entry.runtime_data = coordinator
    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    return True


async def async_unload_entry(
    hass: HomeAssistant, entry: SmartMonitorConfigEntry
) -> bool:
    """Unload a config entry."""
    return await hass.config_entries.async_unload_platforms(entry, PLATFORMS)


async def async_remove_config_entry_device(
    hass: HomeAssistant, entry: SmartMonitorConfigEntry, device: dr.AnyDeviceEntry
) -> bool:
    """Allow removing disks that are no longer attached to the host."""
    return not any(
        domain == DOMAIN
        and (identifier == entry.unique_id or identifier in entry.runtime_data.data)
        for domain, identifier in device.identifiers
    )
