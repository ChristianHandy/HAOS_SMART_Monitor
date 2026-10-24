"""Diagnostics for SMART Disk Monitor."""

from dataclasses import asdict
from typing import Any

from aiosmartctl import Disk

from homeassistant.components.diagnostics import async_redact_data
from homeassistant.const import CONF_HOST, CONF_PASSWORD, CONF_USERNAME
from homeassistant.core import HomeAssistant

from .const import CONF_HOST_KEY, CONF_PRIVATE_KEY
from .coordinator import SmartMonitorConfigEntry

TO_REDACT = {
    CONF_HOST,
    CONF_HOST_KEY,
    CONF_PASSWORD,
    CONF_PRIVATE_KEY,
    CONF_USERNAME,
    "hostname",
    "logical_unit_id",
    "serial",
    "serial_number",
    "wwn",
}


async def async_get_config_entry_diagnostics(
    hass: HomeAssistant, entry: SmartMonitorConfigEntry
) -> dict[str, Any]:
    """Return diagnostics for a config entry."""
    coordinator = entry.runtime_data
    return async_redact_data(
        {
            "entry": {"data": dict(entry.data), "options": dict(entry.options)},
            "host": asdict(coordinator.host_info),
            # Disk IDs contain serial numbers, so list the disks without them.
            "disks": [_disk(disk) for disk in coordinator.data.values()],
        },
        TO_REDACT,
    )


def _disk(disk: Disk) -> dict[str, Any]:
    data = asdict(disk)
    data["supported_self_tests"] = sorted(disk.supported_self_tests)
    return data
