"""Sensors for SMART Disk Monitor."""

from collections.abc import Callable
from dataclasses import dataclass
from typing import override

from aiosmartctl import Disk, HealthStatus, SelfTestResult

from homeassistant.components.sensor import (
    SensorDeviceClass,
    SensorEntity,
    SensorEntityDescription,
    SensorStateClass,
)
from homeassistant.const import (
    PERCENTAGE,
    EntityCategory,
    UnitOfInformation,
    UnitOfTemperature,
    UnitOfTime,
)
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback

from .coordinator import SmartMonitorConfigEntry, SmartMonitorCoordinator
from .entity import (
    SmartMonitorEntity,
    SmartMonitorEntityDescription,
    async_setup_disk_entities,
)

PARALLEL_UPDATES = 0

HEALTH_OPTIONS = [
    HealthStatus.PASSED.value,
    HealthStatus.WARNING.value,
    HealthStatus.FAILED.value,
]
SELF_TEST_OPTIONS = [
    SelfTestResult.PASSED.value,
    SelfTestResult.FAILED.value,
    SelfTestResult.ABORTED.value,
    SelfTestResult.UNKNOWN.value,
]


@dataclass(frozen=True, kw_only=True)
class SmartMonitorSensorEntityDescription(
    SensorEntityDescription, SmartMonitorEntityDescription
):
    """Describes a disk sensor."""

    value_fn: Callable[[Disk], int | str | None]
    exists_fn: Callable[[Disk], bool] = lambda _: True


def _has[T](getter: Callable[[Disk], T | None]) -> Callable[[Disk], bool]:
    return lambda disk: getter(disk) is not None


def _counter(
    key: str,
    getter: Callable[[Disk], int | None],
    *,
    enabled: bool = True,
) -> SmartMonitorSensorEntityDescription:
    """Describe an error counter that only some disks report."""
    return SmartMonitorSensorEntityDescription(
        key=key,
        translation_key=key,
        state_class=SensorStateClass.MEASUREMENT,
        entity_category=EntityCategory.DIAGNOSTIC,
        entity_registry_enabled_default=enabled,
        value_fn=getter,
        exists_fn=_has(getter),
    )


def _last_self_test(disk: Disk) -> str | None:
    if (entry := disk.last_self_test) is None:
        return None
    return entry.result.value


SENSORS: tuple[SmartMonitorSensorEntityDescription, ...] = (
    SmartMonitorSensorEntityDescription(
        key="health",
        translation_key="health",
        device_class=SensorDeviceClass.ENUM,
        options=HEALTH_OPTIONS,
        value_fn=lambda disk: (
            None if disk.health is HealthStatus.UNKNOWN else disk.health.value
        ),
    ),
    SmartMonitorSensorEntityDescription(
        key="temperature",
        device_class=SensorDeviceClass.TEMPERATURE,
        native_unit_of_measurement=UnitOfTemperature.CELSIUS,
        state_class=SensorStateClass.MEASUREMENT,
        value_fn=lambda disk: disk.temperature,
        exists_fn=_has(lambda disk: disk.temperature),
    ),
    SmartMonitorSensorEntityDescription(
        key="percentage_used",
        translation_key="percentage_used",
        native_unit_of_measurement=PERCENTAGE,
        state_class=SensorStateClass.MEASUREMENT,
        value_fn=lambda disk: disk.percentage_used,
        exists_fn=_has(lambda disk: disk.percentage_used),
    ),
    SmartMonitorSensorEntityDescription(
        key="power_on_hours",
        translation_key="power_on_hours",
        device_class=SensorDeviceClass.DURATION,
        native_unit_of_measurement=UnitOfTime.HOURS,
        state_class=SensorStateClass.TOTAL_INCREASING,
        entity_category=EntityCategory.DIAGNOSTIC,
        value_fn=lambda disk: disk.power_on_hours,
        exists_fn=_has(lambda disk: disk.power_on_hours),
    ),
    SmartMonitorSensorEntityDescription(
        key="power_cycles",
        translation_key="power_cycles",
        state_class=SensorStateClass.TOTAL_INCREASING,
        entity_category=EntityCategory.DIAGNOSTIC,
        value_fn=lambda disk: disk.power_cycles,
        exists_fn=_has(lambda disk: disk.power_cycles),
    ),
    SmartMonitorSensorEntityDescription(
        key="last_self_test",
        translation_key="last_self_test",
        device_class=SensorDeviceClass.ENUM,
        options=SELF_TEST_OPTIONS,
        entity_category=EntityCategory.DIAGNOSTIC,
        value_fn=_last_self_test,
        exists_fn=lambda disk: bool(disk.supported_self_tests or disk.self_tests),
    ),
    SmartMonitorSensorEntityDescription(
        key="data_read",
        translation_key="data_read",
        device_class=SensorDeviceClass.DATA_SIZE,
        native_unit_of_measurement=UnitOfInformation.BYTES,
        suggested_unit_of_measurement=UnitOfInformation.TERABYTES,
        suggested_display_precision=2,
        state_class=SensorStateClass.TOTAL_INCREASING,
        entity_category=EntityCategory.DIAGNOSTIC,
        entity_registry_enabled_default=False,
        value_fn=lambda disk: disk.data_read_bytes,
        exists_fn=_has(lambda disk: disk.data_read_bytes),
    ),
    SmartMonitorSensorEntityDescription(
        key="data_written",
        translation_key="data_written",
        device_class=SensorDeviceClass.DATA_SIZE,
        native_unit_of_measurement=UnitOfInformation.BYTES,
        suggested_unit_of_measurement=UnitOfInformation.TERABYTES,
        suggested_display_precision=2,
        state_class=SensorStateClass.TOTAL_INCREASING,
        entity_category=EntityCategory.DIAGNOSTIC,
        value_fn=lambda disk: disk.data_written_bytes,
        exists_fn=_has(lambda disk: disk.data_written_bytes),
    ),
    SmartMonitorSensorEntityDescription(
        key="available_spare",
        translation_key="available_spare",
        native_unit_of_measurement=PERCENTAGE,
        state_class=SensorStateClass.MEASUREMENT,
        entity_category=EntityCategory.DIAGNOSTIC,
        value_fn=lambda disk: disk.available_spare,
        exists_fn=_has(lambda disk: disk.available_spare),
    ),
    _counter("reallocated_sectors", lambda disk: disk.reallocated_sectors),
    _counter("pending_sectors", lambda disk: disk.pending_sectors),
    _counter("offline_uncorrectable", lambda disk: disk.offline_uncorrectable),
    _counter("udma_crc_errors", lambda disk: disk.udma_crc_errors),
    _counter(
        "reported_uncorrectable",
        lambda disk: disk.reported_uncorrectable,
        enabled=False,
    ),
    _counter(
        "reallocation_events", lambda disk: disk.reallocation_events, enabled=False
    ),
    _counter("command_timeouts", lambda disk: disk.command_timeouts, enabled=False),
    _counter("spin_retry_count", lambda disk: disk.spin_retry_count, enabled=False),
    _counter("media_errors", lambda disk: disk.media_errors),
    _counter("unsafe_shutdowns", lambda disk: disk.unsafe_shutdowns, enabled=False),
    _counter("error_log_entries", lambda disk: disk.error_log_entries, enabled=False),
    _counter("grown_defects", lambda disk: disk.grown_defects),
    _counter("uncorrected_read_errors", lambda disk: disk.uncorrected_read_errors),
    _counter("uncorrected_write_errors", lambda disk: disk.uncorrected_write_errors),
    _counter(
        "uncorrected_verify_errors",
        lambda disk: disk.uncorrected_verify_errors,
        enabled=False,
    ),
    _counter("non_medium_errors", lambda disk: disk.non_medium_errors, enabled=False),
)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: SmartMonitorConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    """Set up sensors for all disks."""
    async_setup_disk_entities(
        entry.runtime_data, async_add_entities, SENSORS, SmartMonitorSensorEntity
    )


class SmartMonitorSensorEntity(SmartMonitorEntity, SensorEntity):
    """A SMART value of a disk."""

    entity_description: SmartMonitorSensorEntityDescription

    def __init__(
        self,
        coordinator: SmartMonitorCoordinator,
        disk_id: str,
        description: SmartMonitorSensorEntityDescription,
    ) -> None:
        """Initialize the sensor."""
        super().__init__(coordinator, disk_id, description)

    @property
    @override
    def native_value(self) -> int | str | None:
        """Return the value."""
        return self.entity_description.value_fn(self.disk)
