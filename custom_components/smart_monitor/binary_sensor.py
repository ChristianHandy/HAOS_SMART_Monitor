"""Binary sensors for SMART Disk Monitor."""

from collections.abc import Callable
from dataclasses import dataclass
from typing import override

from aiosmartctl import Disk, HealthStatus

from homeassistant.components.binary_sensor import (
    BinarySensorDeviceClass,
    BinarySensorEntity,
    BinarySensorEntityDescription,
)
from homeassistant.const import EntityCategory
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback

from .coordinator import SmartMonitorConfigEntry, SmartMonitorCoordinator
from .entity import (
    SmartMonitorEntity,
    SmartMonitorEntityDescription,
    async_setup_disk_entities,
)

PARALLEL_UPDATES = 0


@dataclass(frozen=True, kw_only=True)
class SmartMonitorBinarySensorEntityDescription(
    BinarySensorEntityDescription, SmartMonitorEntityDescription
):
    """Describes a disk binary sensor."""

    is_on_fn: Callable[[Disk], bool | None]
    exists_fn: Callable[[Disk], bool] = lambda _: True


def _health_problem(disk: Disk) -> bool | None:
    if disk.health is HealthStatus.UNKNOWN:
        return None
    return disk.health is not HealthStatus.PASSED


_BAD_SECTOR_COUNTS: tuple[Callable[[Disk], int | None], ...] = (
    lambda disk: disk.reallocated_sectors,
    lambda disk: disk.pending_sectors,
    lambda disk: disk.offline_uncorrectable,
    lambda disk: disk.grown_defects,
    lambda disk: disk.media_errors,
)


def _sector_problem(disk: Disk) -> bool | None:
    counts = [
        count for getter in _BAD_SECTOR_COUNTS if (count := getter(disk)) is not None
    ]
    if not counts:
        return None
    return any(counts)


BINARY_SENSORS: tuple[SmartMonitorBinarySensorEntityDescription, ...] = (
    SmartMonitorBinarySensorEntityDescription(
        key="health_problem",
        translation_key="health_problem",
        device_class=BinarySensorDeviceClass.PROBLEM,
        is_on_fn=_health_problem,
    ),
    SmartMonitorBinarySensorEntityDescription(
        key="sector_problem",
        translation_key="sector_problem",
        device_class=BinarySensorDeviceClass.PROBLEM,
        is_on_fn=_sector_problem,
        exists_fn=lambda disk: _sector_problem(disk) is not None,
    ),
    SmartMonitorBinarySensorEntityDescription(
        key="self_test_running",
        translation_key="self_test_running",
        device_class=BinarySensorDeviceClass.RUNNING,
        entity_category=EntityCategory.DIAGNOSTIC,
        is_on_fn=lambda disk: disk.self_test_in_progress,
        exists_fn=lambda disk: bool(disk.supported_self_tests),
    ),
    SmartMonitorBinarySensorEntityDescription(
        key="standby",
        translation_key="standby",
        entity_category=EntityCategory.DIAGNOSTIC,
        is_on_fn=lambda disk: disk.standby,
    ),
)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: SmartMonitorConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    """Set up binary sensors for all disks."""
    async_setup_disk_entities(
        entry.runtime_data,
        async_add_entities,
        BINARY_SENSORS,
        SmartMonitorBinarySensorEntity,
    )


class SmartMonitorBinarySensorEntity(SmartMonitorEntity, BinarySensorEntity):
    """A binary state of a disk."""

    entity_description: SmartMonitorBinarySensorEntityDescription

    def __init__(
        self,
        coordinator: SmartMonitorCoordinator,
        disk_id: str,
        description: SmartMonitorBinarySensorEntityDescription,
    ) -> None:
        """Initialize the binary sensor."""
        super().__init__(coordinator, disk_id, description)

    @property
    @override
    def is_on(self) -> bool | None:
        """Return the state."""
        return self.entity_description.is_on_fn(self.disk)
