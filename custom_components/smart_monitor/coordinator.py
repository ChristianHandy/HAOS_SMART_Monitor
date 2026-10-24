"""Data update coordinator for SMART Disk Monitor."""

from dataclasses import replace
from typing import override

from aiosmartctl import (
    DeviceSpec,
    Disk,
    HostInfo,
    SmartctlAuthenticationError,
    SmartctlClient,
    SmartctlError,
    SmartctlHostKeyError,
)

from homeassistant.config_entries import ConfigEntry
from homeassistant.const import CONF_DEVICES
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import ConfigEntryAuthFailed
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed

from .const import (
    CONF_SKIP_STANDBY,
    DEFAULT_SKIP_STANDBY,
    DOMAIN,
    LOGGER,
    SCAN_INTERVAL,
)

type SmartMonitorConfigEntry = ConfigEntry[SmartMonitorCoordinator]


class SmartMonitorCoordinator(DataUpdateCoordinator[dict[str, Disk]]):
    """Reads SMART data of all disks of one host.

    The data maps a stable disk ID, based on the WWN or serial number, to the
    latest reading of that disk.
    """

    config_entry: SmartMonitorConfigEntry
    host_info: HostInfo
    host_device_id: str

    def __init__(
        self,
        hass: HomeAssistant,
        config_entry: SmartMonitorConfigEntry,
        client: SmartctlClient,
    ) -> None:
        """Initialize the coordinator."""
        super().__init__(
            hass,
            LOGGER,
            config_entry=config_entry,
            name=DOMAIN,
            update_interval=SCAN_INTERVAL,
        )
        self.client = client
        self._disk_ids: dict[str, str] = {}

    @override
    async def _async_setup(self) -> None:
        """Read information about the host once."""
        try:
            async with self.client.session() as session:
                self.host_info = await session.get_host_info()
        except (SmartctlAuthenticationError, SmartctlHostKeyError) as err:
            raise ConfigEntryAuthFailed(
                translation_domain=DOMAIN,
                translation_key=_auth_error_key(err),
            ) from err
        except SmartctlError as err:
            raise UpdateFailed(
                translation_domain=DOMAIN,
                translation_key="update_failed",
                translation_placeholders={"error": str(err)},
            ) from err

    @override
    async def _async_update_data(self) -> dict[str, Disk]:
        """Read all disks."""
        options = self.config_entry.options
        specs = [DeviceSpec.parse(value) for value in options.get(CONF_DEVICES, [])]
        try:
            async with self.client.session() as session:
                disks = await session.get_disks(
                    specs or None,
                    skip_standby=options.get(CONF_SKIP_STANDBY, DEFAULT_SKIP_STANDBY),
                )
        except (SmartctlAuthenticationError, SmartctlHostKeyError) as err:
            raise ConfigEntryAuthFailed(
                translation_domain=DOMAIN,
                translation_key=_auth_error_key(err),
            ) from err
        except SmartctlError as err:
            raise UpdateFailed(
                translation_domain=DOMAIN,
                translation_key="update_failed",
                translation_placeholders={"error": str(err)},
            ) from err

        previous = self.data or {}
        result: dict[str, Disk] = {}
        for disk in disks:
            disk_id = disk.identifier or self._disk_ids.get(disk.spec.key)
            if disk_id is None:
                if disk.standby or disk.error:
                    LOGGER.debug(
                        "Skipping %s until it can be read: %s",
                        disk.spec.key,
                        disk.error or "in standby",
                    )
                    continue
                # Some USB bridges hide the serial number; fall back to the path.
                disk_id = f"{self.config_entry.unique_id}_{disk.spec.key}"
            self._disk_ids[disk.spec.key] = disk_id
            if old := previous.get(disk_id):
                # Keep the last reading of a sleeping or unreadable disk, so
                # values do not flap while the disk sleeps.
                if disk.standby:
                    disk = replace(old, spec=disk.spec, standby=True, error=None)
                elif disk.error:
                    disk = replace(old, spec=disk.spec, error=disk.error)
            elif disk.error:
                LOGGER.warning("Cannot read %s: %s", disk.spec.key, disk.error)
                continue
            result[disk_id] = disk
        return result


def _auth_error_key(err: SmartctlError) -> str:
    if isinstance(err, SmartctlHostKeyError):
        return "host_key_changed"
    return "invalid_auth"
