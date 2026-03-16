"""Sensor platform for SMART Disk Monitor."""
from __future__ import annotations

import logging
from typing import Any

from homeassistant.components.sensor import (
    SensorDeviceClass,
    SensorEntity,
    SensorEntityDescription,
    SensorStateClass,
)
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import UnitOfTemperature, UnitOfTime
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity import DeviceInfo
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import DOMAIN, CONF_HOST, CONF_SERVER_TYPE, SMART_ATTRS, NVME_ATTRS
from .coordinator import SmartMonitorCoordinator
from .smart_fetcher import DiskSmartData

_LOGGER = logging.getLogger(__name__)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up SMART sensors from a config entry."""
    coordinator: SmartMonitorCoordinator = hass.data[DOMAIN][entry.entry_id]

    entities: list[SensorEntity] = []
    host = entry.data[CONF_HOST]
    server_type = entry.data.get(CONF_SERVER_TYPE, "generic_linux")

    if coordinator.data:
        for device, disk_data in coordinator.data.items():
            # Core sensors for every disk
            entities.append(DiskHealthSensor(coordinator, entry, device, host, server_type))
            entities.append(DiskTemperatureSensor(coordinator, entry, device, host, server_type))
            entities.append(DiskPowerOnHoursSensor(coordinator, entry, device, host, server_type))
            entities.append(DiskPowerCyclesSensor(coordinator, entry, device, host, server_type))

            # HDD/SSD specific
            if disk_data.disk_type in ("HDD", "SSD"):
                entities.append(DiskReallocatedSectorsSensor(coordinator, entry, device, host, server_type))
                entities.append(DiskPendingSectorsSensor(coordinator, entry, device, host, server_type))
                entities.append(DiskUncorrectableSectorsSensor(coordinator, entry, device, host, server_type))

            # NVMe specific
            if disk_data.disk_type == "NVMe":
                for key in ("available_spare", "percentage_used", "media_errors"):
                    entities.append(DiskNvmeAttributeSensor(coordinator, entry, device, host, server_type, key))

    async_add_entities(entities, True)


# ---------------------------------------------------------------------------
# Base class
# ---------------------------------------------------------------------------

class DiskSensorBase(CoordinatorEntity[SmartMonitorCoordinator], SensorEntity):
    """Base sensor for a single disk on a remote server."""

    _attr_has_entity_name = True

    def __init__(
        self,
        coordinator: SmartMonitorCoordinator,
        entry: ConfigEntry,
        device: str,
        host: str,
        server_type: str,
    ) -> None:
        super().__init__(coordinator)
        self._device = device
        self._host = host
        self._server_type = server_type
        self._entry = entry

        # Unique device slug e.g. "sda" or "nvme0n1"
        self._dev_slug = device.replace("/dev/", "").replace("/", "_")

    @property
    def _disk_data(self) -> DiskSmartData | None:
        if self.coordinator.data:
            return self.coordinator.data.get(self._device)
        return None

    @property
    def device_info(self) -> DeviceInfo:
        disk = self._disk_data
        model = disk.model if disk else "Unknown"
        serial = disk.serial if disk else "Unknown"
        return DeviceInfo(
            identifiers={(DOMAIN, f"{self._host}_{self._dev_slug}")},
            name=f"{self._host} – {self._device}",
            manufacturer=self._server_type.capitalize(),
            model=model,
            sw_version=disk.firmware if disk else None,
            via_device=(DOMAIN, self._host),
            configuration_url=f"ssh://{self._host}",
        )

    @property
    def available(self) -> bool:
        disk = self._disk_data
        return disk is not None and disk.error is None


# ---------------------------------------------------------------------------
# Concrete sensors
# ---------------------------------------------------------------------------

class DiskHealthSensor(DiskSensorBase):
    """Overall SMART health status."""

    def __init__(self, coordinator, entry, device, host, server_type):
        super().__init__(coordinator, entry, device, host, server_type)
        self._attr_unique_id = f"{host}_{self._dev_slug}_health"
        self._attr_name = "Health"
        self._attr_icon = "mdi:harddisk"

    @property
    def native_value(self) -> str | None:
        disk = self._disk_data
        return disk.health if disk else None

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        disk = self._disk_data
        if not disk:
            return {}
        return {
            "device": disk.device,
            "model": disk.model,
            "serial": disk.serial,
            "firmware": disk.firmware,
            "capacity": disk.capacity,
            "disk_type": disk.disk_type,
            "rpm": disk.rpm,
            "host": self._host,
            "server_type": self._server_type,
        }


class DiskTemperatureSensor(DiskSensorBase):
    """Disk temperature sensor."""

    _attr_device_class = SensorDeviceClass.TEMPERATURE
    _attr_state_class = SensorStateClass.MEASUREMENT
    _attr_native_unit_of_measurement = UnitOfTemperature.CELSIUS

    def __init__(self, coordinator, entry, device, host, server_type):
        super().__init__(coordinator, entry, device, host, server_type)
        self._attr_unique_id = f"{host}_{self._dev_slug}_temperature"
        self._attr_name = "Temperature"

    @property
    def native_value(self) -> int | None:
        disk = self._disk_data
        return disk.temperature if disk else None


class DiskPowerOnHoursSensor(DiskSensorBase):
    """Power-on hours sensor."""

    _attr_state_class = SensorStateClass.TOTAL_INCREASING
    _attr_native_unit_of_measurement = UnitOfTime.HOURS
    _attr_icon = "mdi:clock-outline"

    def __init__(self, coordinator, entry, device, host, server_type):
        super().__init__(coordinator, entry, device, host, server_type)
        self._attr_unique_id = f"{host}_{self._dev_slug}_power_on_hours"
        self._attr_name = "Power On Hours"

    @property
    def native_value(self) -> int | None:
        disk = self._disk_data
        return disk.power_on_hours if disk else None


class DiskPowerCyclesSensor(DiskSensorBase):
    """Power cycle count sensor."""

    _attr_state_class = SensorStateClass.TOTAL_INCREASING
    _attr_icon = "mdi:power"

    def __init__(self, coordinator, entry, device, host, server_type):
        super().__init__(coordinator, entry, device, host, server_type)
        self._attr_unique_id = f"{host}_{self._dev_slug}_power_cycles"
        self._attr_name = "Power Cycles"

    @property
    def native_value(self) -> int | None:
        disk = self._disk_data
        return disk.power_cycles if disk else None


class DiskReallocatedSectorsSensor(DiskSensorBase):
    """Reallocated sectors count (HDD/SSD)."""

    _attr_state_class = SensorStateClass.TOTAL_INCREASING
    _attr_icon = "mdi:alert"

    def __init__(self, coordinator, entry, device, host, server_type):
        super().__init__(coordinator, entry, device, host, server_type)
        self._attr_unique_id = f"{host}_{self._dev_slug}_reallocated_sectors"
        self._attr_name = "Reallocated Sectors"

    @property
    def native_value(self) -> int | None:
        disk = self._disk_data
        return disk.reallocated_sectors if disk else None


class DiskPendingSectorsSensor(DiskSensorBase):
    """Current pending sectors (HDD/SSD)."""

    _attr_state_class = SensorStateClass.MEASUREMENT
    _attr_icon = "mdi:alert-outline"

    def __init__(self, coordinator, entry, device, host, server_type):
        super().__init__(coordinator, entry, device, host, server_type)
        self._attr_unique_id = f"{host}_{self._dev_slug}_pending_sectors"
        self._attr_name = "Pending Sectors"

    @property
    def native_value(self) -> int | None:
        disk = self._disk_data
        return disk.pending_sectors if disk else None


class DiskUncorrectableSectorsSensor(DiskSensorBase):
    """Offline uncorrectable sectors (HDD/SSD)."""

    _attr_state_class = SensorStateClass.TOTAL_INCREASING
    _attr_icon = "mdi:close-circle-outline"

    def __init__(self, coordinator, entry, device, host, server_type):
        super().__init__(coordinator, entry, device, host, server_type)
        self._attr_unique_id = f"{host}_{self._dev_slug}_uncorrectable_sectors"
        self._attr_name = "Uncorrectable Sectors"

    @property
    def native_value(self) -> int | None:
        disk = self._disk_data
        return disk.uncorrectable_sectors if disk else None


class DiskNvmeAttributeSensor(DiskSensorBase):
    """NVMe attribute sensor."""

    def __init__(self, coordinator, entry, device, host, server_type, attr_key: str):
        super().__init__(coordinator, entry, device, host, server_type)
        meta = NVME_ATTRS.get(attr_key, {"name": attr_key, "icon": "mdi:information", "unit": ""})
        self._attr_key = attr_key
        self._attr_unique_id = f"{host}_{self._dev_slug}_nvme_{attr_key}"
        self._attr_name = meta["name"]
        self._attr_icon = meta["icon"]
        if meta["unit"]:
            self._attr_native_unit_of_measurement = meta["unit"]
        self._attr_state_class = SensorStateClass.MEASUREMENT

    @property
    def native_value(self) -> Any:
        disk = self._disk_data
        if not disk:
            return None
        attr = disk.nvme_attributes.get(self._attr_key, {})
        return attr.get("value")
