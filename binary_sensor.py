"""Binary sensor platform for SMART Disk Monitor – disk health alerts."""
from __future__ import annotations

from homeassistant.components.binary_sensor import (
    BinarySensorDeviceClass,
    BinarySensorEntity,
)
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity import DeviceInfo
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import DOMAIN, CONF_HOST, CONF_SERVER_TYPE, HEALTH_FAILED
from .coordinator import SmartMonitorCoordinator
from .smart_fetcher import DiskSmartData
from .sensor import _device_display_name, _manufacturer_from_model


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    coordinator: SmartMonitorCoordinator = hass.data[DOMAIN][entry.entry_id]
    host = entry.data[CONF_HOST]
    server_type = entry.data.get(CONF_SERVER_TYPE, "generic_linux")

    entities = []
    devices = list(coordinator.data.keys()) if coordinator.data else []
    for device in devices:
        entities.append(DiskHealthBinarySensor(coordinator, entry, device, host, server_type))
        entities.append(DiskProblemBinarySensor(coordinator, entry, device, host, server_type))

    async_add_entities(entities, True)

    _known: set[str] = set(devices)

    def _check_new_devices() -> None:
        nonlocal _known
        if not coordinator.data:
            return
        new_devices = set(coordinator.data.keys()) - _known
        if not new_devices:
            return
        _known.update(new_devices)
        new_ents = []
        for dev in new_devices:
            new_ents.append(DiskHealthBinarySensor(coordinator, entry, dev, host, server_type))
            new_ents.append(DiskProblemBinarySensor(coordinator, entry, dev, host, server_type))
        async_add_entities(new_ents, True)

    coordinator.async_add_listener(_check_new_devices)


class _DiskBinarySensorBase(CoordinatorEntity[SmartMonitorCoordinator], BinarySensorEntity):
    _attr_has_entity_name = True

    def __init__(self, coordinator, entry, device, host, server_type):
        super().__init__(coordinator)
        self._device = device
        self._host = host
        self._server_type = server_type
        self._dev_slug = device.replace("/dev/", "").replace("/", "_")

    @property
    def _disk_data(self) -> DiskSmartData | None:
        if self.coordinator.data:
            return self.coordinator.data.get(self._device)
        return None

    @property
    def device_info(self) -> DeviceInfo:
        disk = self._disk_data
        name = _device_display_name(disk, self._device)
        manufacturer = _manufacturer_from_model(disk.model if disk else "Unknown")
        return DeviceInfo(
            identifiers={(DOMAIN, f"{self._host}_{self._dev_slug}")},
            name=name,
            manufacturer=manufacturer,
            model=disk.model if disk else None,
            serial_number=disk.serial if (disk and disk.serial != "Unknown") else None,
        )

    @property
    def available(self) -> bool:
        disk = self._disk_data
        return disk is not None and disk.error is None


class DiskHealthBinarySensor(_DiskBinarySensorBase):
    """True when SMART health test FAILED."""

    _attr_device_class = BinarySensorDeviceClass.PROBLEM

    def __init__(self, coordinator, entry, device, host, server_type):
        super().__init__(coordinator, entry, device, host, server_type)
        self._attr_unique_id = f"{host}_{self._dev_slug}_health_problem"
        self._attr_name = "Health Problem"
        self._attr_icon = "mdi:harddisk-remove"

    @property
    def is_on(self) -> bool | None:
        disk = self._disk_data
        if disk is None:
            return None
        return disk.health == HEALTH_FAILED


class DiskProblemBinarySensor(_DiskBinarySensorBase):
    """True when reallocated, pending, or uncorrectable sector count > 0."""

    _attr_device_class = BinarySensorDeviceClass.PROBLEM

    def __init__(self, coordinator, entry, device, host, server_type):
        super().__init__(coordinator, entry, device, host, server_type)
        self._attr_unique_id = f"{host}_{self._dev_slug}_sector_problem"
        self._attr_name = "Sector Problem"
        self._attr_icon = "mdi:alert-circle"

    @property
    def is_on(self) -> bool | None:
        disk = self._disk_data
        if disk is None:
            return None
        bad = (
            (disk.reallocated_sectors or 0)
            + (disk.pending_sectors or 0)
            + (disk.uncorrectable_sectors or 0)
        )
        return bad > 0

    @property
    def extra_state_attributes(self) -> dict:
        disk = self._disk_data
        if not disk:
            return {}
        return {
            "reallocated_sectors": disk.reallocated_sectors,
            "pending_sectors": disk.pending_sectors,
            "uncorrectable_sectors": disk.uncorrectable_sectors,
        }
