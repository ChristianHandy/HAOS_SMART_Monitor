"""Sensor platform for SMART Disk Monitor."""
from __future__ import annotations

import logging
from typing import Any

from homeassistant.components.sensor import (
    SensorDeviceClass,
    SensorEntity,
    SensorStateClass,
)
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import UnitOfTemperature, UnitOfTime, PERCENTAGE
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity import DeviceInfo
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import DOMAIN, CONF_HOST, CONF_SERVER_TYPE, NVME_ATTRS
from .coordinator import SmartMonitorCoordinator
from .smart_fetcher import DiskSmartData

_LOGGER = logging.getLogger(__name__)


def _device_display_name(disk: DiskSmartData | None, device: str) -> str:
    """Return a human-friendly device name: 'Model SN:Serial'."""
    if disk and disk.model != "Unknown" and disk.serial != "Unknown":
        return f"{disk.model}  ·  {disk.serial}"
    if disk and disk.model != "Unknown":
        return disk.model
    if disk and disk.serial != "Unknown":
        return disk.serial
    return device  # fallback to /dev/sdX


def _manufacturer_from_model(model: str) -> str:
    """Best-effort manufacturer extraction from model string."""
    known = {
        "WD": "Western Digital", "Western Digital": "Western Digital",
        "Seagate": "Seagate", "ST": "Seagate",
        "Samsung": "Samsung", "SAMSUNG": "Samsung",
        "Toshiba": "Toshiba", "TOSHIBA": "Toshiba",
        "Hitachi": "Hitachi", "HITACHI": "Hitachi",
        "HGST": "HGST",
        "Kingston": "Kingston", "KINGSTON": "Kingston",
        "Crucial": "Crucial", "CRUCIAL": "Crucial",
        "Intel": "Intel", "INTEL": "Intel",
        "SanDisk": "SanDisk", "SANDISK": "SanDisk",
        "ORICO": "ORICO",
        "Corsair": "Corsair", "CORSAIR": "Corsair",
    }
    for key, val in known.items():
        if model.startswith(key) or key in model:
            return val
    return model.split()[0] if model and model != "Unknown" else "Unknown"


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    coordinator: SmartMonitorCoordinator = hass.data[DOMAIN][entry.entry_id]
    host = entry.data[CONF_HOST]
    server_type = entry.data.get(CONF_SERVER_TYPE, "generic_linux")

    def _build_sensors_for_device(device: str, disk_data: DiskSmartData) -> list[SensorEntity]:
        ents: list[SensorEntity] = [
            DiskHealthSensor(coordinator, entry, device, host, server_type),
            DiskTemperatureSensor(coordinator, entry, device, host, server_type),
            DiskPowerOnHoursSensor(coordinator, entry, device, host, server_type),
            DiskPowerOnDaysSensor(coordinator, entry, device, host, server_type),
            DiskPowerCyclesSensor(coordinator, entry, device, host, server_type),
            DiskLastTestSensor(coordinator, entry, device, host, server_type),
        ]
        if disk_data.disk_type in ("HDD", "SSD"):
            ents += [
                DiskReallocatedSectorsSensor(coordinator, entry, device, host, server_type),
                DiskPendingSectorsSensor(coordinator, entry, device, host, server_type),
                DiskUncorrectableSectorsSensor(coordinator, entry, device, host, server_type),
            ]
        if disk_data.disk_type == "HDD":
            ents += [
                DiskSeekErrorRateSensor(coordinator, entry, device, host, server_type),
                DiskSpinRetryCountSensor(coordinator, entry, device, host, server_type),
            ]
        if disk_data.disk_type in ("HDD", "SSD"):
            ents += [
                DiskCommandTimeoutSensor(coordinator, entry, device, host, server_type),
                DiskUdmaCrcErrorsSensor(coordinator, entry, device, host, server_type),
            ]
        if disk_data.disk_type in ("SSD", "NVMe"):
            ents.append(DiskSsdLifeLeftSensor(coordinator, entry, device, host, server_type))
        if disk_data.disk_type == "SSD":
            ents.append(DiskWearLevelingSensor(coordinator, entry, device, host, server_type))
        if disk_data.disk_type == "NVMe":
            for key in ("available_spare", "percentage_used", "media_errors",
                        "power_on_hours", "power_cycles", "unsafe_shutdowns",
                        "num_err_log_entries"):
                ents.append(DiskNvmeAttributeSensor(coordinator, entry, device, host, server_type, key))
        return ents

    entities: list[SensorEntity] = []
    if coordinator.data:
        for device, disk_data in coordinator.data.items():
            entities.extend(_build_sensors_for_device(device, disk_data))

    async_add_entities(entities, True)

    _known: set[str] = set(coordinator.data.keys()) if coordinator.data else set()

    def _check_new_devices() -> None:
        nonlocal _known
        if not coordinator.data:
            return
        new_devices = set(coordinator.data.keys()) - _known
        if not new_devices:
            return
        _known.update(new_devices)
        new_ents: list[SensorEntity] = []
        for dev in new_devices:
            new_ents.extend(_build_sensors_for_device(dev, coordinator.data[dev]))
        async_add_entities(new_ents, True)

    entry.async_on_unload(coordinator.async_add_listener(_check_new_devices))


# ---------------------------------------------------------------------------
# Base class
# ---------------------------------------------------------------------------

class DiskSensorBase(CoordinatorEntity[SmartMonitorCoordinator], SensorEntity):
    _attr_has_entity_name = True

    def __init__(self, coordinator, entry, device, host, server_type) -> None:
        super().__init__(coordinator)
        self._device = device
        self._host = host
        self._server_type = server_type
        self._entry = entry
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
            sw_version=disk.firmware if (disk and disk.firmware != "Unknown") else None,
            hw_version=disk.capacity if (disk and disk.capacity != "Unknown") else None,
        )

    @property
    def available(self) -> bool:
        disk = self._disk_data
        return disk is not None and disk.error is None


# ---------------------------------------------------------------------------
# Sensors
# ---------------------------------------------------------------------------

class DiskHealthSensor(DiskSensorBase):
    def __init__(self, coordinator, entry, device, host, server_type):
        super().__init__(coordinator, entry, device, host, server_type)
        self._attr_unique_id = f"{host}_{self._dev_slug}_health"
        self._attr_name = "Health"

    @property
    def native_value(self) -> str | None:
        disk = self._disk_data
        return disk.health if disk else None

    @property
    def icon(self) -> str:
        disk = self._disk_data
        if disk and disk.health == "PASSED":
            return "mdi:harddisk"
        if disk and disk.health == "FAILED":
            return "mdi:harddisk-remove"
        return "mdi:harddisk-plus"

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        disk = self._disk_data
        if not disk:
            return {}
        return {
            "device_path": disk.device,
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

    @property
    def icon(self) -> str:
        disk = self._disk_data
        temp = disk.temperature if disk else None
        if temp is None:
            return "mdi:thermometer"
        if temp >= 55:
            return "mdi:thermometer-alert"
        if temp >= 45:
            return "mdi:thermometer-high"
        return "mdi:thermometer"


class DiskPowerOnHoursSensor(DiskSensorBase):
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


class DiskPowerOnDaysSensor(DiskSensorBase):
    """Derived sensor: power-on hours expressed as days for readability."""
    _attr_state_class = SensorStateClass.TOTAL_INCREASING
    _attr_icon = "mdi:calendar-clock"

    def __init__(self, coordinator, entry, device, host, server_type):
        super().__init__(coordinator, entry, device, host, server_type)
        self._attr_unique_id = f"{host}_{self._dev_slug}_power_on_days"
        self._attr_name = "Power On Days"
        self._attr_native_unit_of_measurement = "d"

    @property
    def native_value(self) -> float | None:
        disk = self._disk_data
        if not disk or disk.power_on_hours is None:
            return None
        return round(disk.power_on_hours / 24, 1)

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        disk = self._disk_data
        if not disk or disk.power_on_hours is None:
            return {}
        years = disk.power_on_hours / 8760
        return {"years": round(years, 2)}


class DiskPowerCyclesSensor(DiskSensorBase):
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

    @property
    def icon(self) -> str:
        disk = self._disk_data
        val = disk.reallocated_sectors if disk else 0
        return "mdi:alert" if val else "mdi:check-circle-outline"


class DiskPendingSectorsSensor(DiskSensorBase):
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


class DiskSeekErrorRateSensor(DiskSensorBase):
    _attr_state_class = SensorStateClass.MEASUREMENT
    _attr_icon = "mdi:magnify-scan"

    def __init__(self, coordinator, entry, device, host, server_type):
        super().__init__(coordinator, entry, device, host, server_type)
        self._attr_unique_id = f"{host}_{self._dev_slug}_seek_error_rate"
        self._attr_name = "Seek Error Rate"

    @property
    def native_value(self) -> int | None:
        disk = self._disk_data
        return disk.seek_error_rate if disk else None


class DiskSpinRetryCountSensor(DiskSensorBase):
    _attr_state_class = SensorStateClass.TOTAL_INCREASING
    _attr_icon = "mdi:rotate-right"

    def __init__(self, coordinator, entry, device, host, server_type):
        super().__init__(coordinator, entry, device, host, server_type)
        self._attr_unique_id = f"{host}_{self._dev_slug}_spin_retry_count"
        self._attr_name = "Spin Retry Count"

    @property
    def native_value(self) -> int | None:
        disk = self._disk_data
        return disk.spin_retry_count if disk else None


class DiskCommandTimeoutSensor(DiskSensorBase):
    _attr_state_class = SensorStateClass.TOTAL_INCREASING
    _attr_icon = "mdi:timer-off-outline"

    def __init__(self, coordinator, entry, device, host, server_type):
        super().__init__(coordinator, entry, device, host, server_type)
        self._attr_unique_id = f"{host}_{self._dev_slug}_command_timeout"
        self._attr_name = "Command Timeout"

    @property
    def native_value(self) -> int | None:
        disk = self._disk_data
        return disk.command_timeout if disk else None


class DiskUdmaCrcErrorsSensor(DiskSensorBase):
    _attr_state_class = SensorStateClass.TOTAL_INCREASING
    _attr_icon = "mdi:lan-disconnect"

    def __init__(self, coordinator, entry, device, host, server_type):
        super().__init__(coordinator, entry, device, host, server_type)
        self._attr_unique_id = f"{host}_{self._dev_slug}_udma_crc_errors"
        self._attr_name = "UDMA CRC Errors"

    @property
    def native_value(self) -> int | None:
        disk = self._disk_data
        return disk.udma_crc_errors if disk else None

    @property
    def icon(self) -> str:
        disk = self._disk_data
        val = disk.udma_crc_errors if disk else 0
        return "mdi:lan-disconnect" if val else "mdi:lan-check"


class DiskSsdLifeLeftSensor(DiskSensorBase):
    _attr_state_class = SensorStateClass.MEASUREMENT
    _attr_native_unit_of_measurement = PERCENTAGE
    _attr_icon = "mdi:battery-heart-variant"

    def __init__(self, coordinator, entry, device, host, server_type):
        super().__init__(coordinator, entry, device, host, server_type)
        self._attr_unique_id = f"{host}_{self._dev_slug}_ssd_life_left"
        self._attr_name = "SSD Life Left"

    @property
    def native_value(self) -> int | None:
        disk = self._disk_data
        return disk.ssd_life_left if disk else None

    @property
    def icon(self) -> str:
        disk = self._disk_data
        val = disk.ssd_life_left if disk else 100
        if val is None:
            return "mdi:battery-heart-variant"
        if val > 70:
            return "mdi:battery-heart-variant"
        if val > 30:
            return "mdi:battery-medium"
        return "mdi:battery-alert"


class DiskWearLevelingSensor(DiskSensorBase):
    _attr_state_class = SensorStateClass.MEASUREMENT
    _attr_icon = "mdi:chart-line-variant"

    def __init__(self, coordinator, entry, device, host, server_type):
        super().__init__(coordinator, entry, device, host, server_type)
        self._attr_unique_id = f"{host}_{self._dev_slug}_wear_leveling"
        self._attr_name = "Wear Leveling Count"

    @property
    def native_value(self) -> int | None:
        disk = self._disk_data
        return disk.wear_leveling if disk else None


class DiskNvmeAttributeSensor(DiskSensorBase):
    def __init__(self, coordinator, entry, device, host, server_type, attr_key: str):
        super().__init__(coordinator, entry, device, host, server_type)
        meta = NVME_ATTRS.get(attr_key, {"name": attr_key, "icon": "mdi:information", "unit": ""})
        self._attr_key = attr_key
        self._attr_unique_id = f"{host}_{self._dev_slug}_nvme_{attr_key}"
        self._attr_name = meta["name"]
        self._attr_icon = meta["icon"]
        if meta.get("unit"):
            self._attr_native_unit_of_measurement = meta["unit"]
        self._attr_state_class = SensorStateClass.MEASUREMENT

    @property
    def native_value(self) -> Any:
        disk = self._disk_data
        if not disk:
            return None
        attr = disk.nvme_attributes.get(self._attr_key, {})
        return attr.get("value")


class DiskLastTestSensor(DiskSensorBase):
    _attr_icon = "mdi:clipboard-check-outline"

    def __init__(self, coordinator, entry, device, host, server_type):
        super().__init__(coordinator, entry, device, host, server_type)
        self._attr_unique_id = f"{host}_{self._dev_slug}_last_test"
        self._attr_name = "Last Self-Test"

    @property
    def native_value(self) -> str | None:
        disk = self._disk_data
        if not disk or disk.last_test_result is None:
            return "Never"
        return disk.last_test_result

    @property
    def icon(self) -> str:
        disk = self._disk_data
        result = disk.last_test_result if disk else None
        if result is None or result == "Never":
            return "mdi:clipboard-outline"
        if "without error" in (result or "").lower():
            return "mdi:clipboard-check"
        if "fail" in (result or "").lower():
            return "mdi:clipboard-alert"
        return "mdi:clipboard-clock-outline"

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        disk = self._disk_data
        if not disk:
            return {}
        return {
            "last_test_type": disk.last_test_type,
            "last_test_date": disk.last_test_date,
            "last_test_remaining_percent": disk.last_test_remaining,
            "test_log": disk.test_log[:10],
        }
