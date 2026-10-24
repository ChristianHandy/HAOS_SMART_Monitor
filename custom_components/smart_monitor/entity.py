"""Base entity for SMART Disk Monitor."""

from collections.abc import Callable, Sequence
from dataclasses import dataclass
from typing import override

from aiosmartctl import Disk

from homeassistant.core import callback
from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.entity import Entity, EntityDescription
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import DOMAIN
from .coordinator import SmartMonitorCoordinator


@dataclass(frozen=True, kw_only=True)
class SmartMonitorEntityDescription(EntityDescription):
    """Describes a disk entity."""

    exists_fn: Callable[[Disk], bool]


class SmartMonitorEntity(CoordinatorEntity[SmartMonitorCoordinator]):
    """An entity that belongs to one disk."""

    _attr_has_entity_name = True

    def __init__(
        self,
        coordinator: SmartMonitorCoordinator,
        disk_id: str,
        description: SmartMonitorEntityDescription,
    ) -> None:
        """Initialize the entity."""
        super().__init__(coordinator)
        self.entity_description = description
        self.disk_id = disk_id
        self._attr_unique_id = f"{disk_id}_{description.key}"
        disk = coordinator.data[disk_id]
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, disk_id)},
            name=disk.model or disk.spec.path,
            manufacturer=disk.vendor,
            model=disk.model,
            serial_number=disk.serial,
            sw_version=disk.firmware,
            via_device_id=coordinator.host_device_id,
        )

    @property
    def disk(self) -> Disk:
        """Return the latest reading of the disk."""
        return self.coordinator.data[self.disk_id]

    @property
    @override
    def available(self) -> bool:
        """Return if the disk could be read."""
        return (
            super().available
            and self.disk_id in self.coordinator.data
            and self.disk.error is None
        )


def async_setup_disk_entities[_DescriptionT: SmartMonitorEntityDescription](
    coordinator: SmartMonitorCoordinator,
    async_add_entities: AddConfigEntryEntitiesCallback,
    descriptions: Sequence[_DescriptionT],
    entity_factory: Callable[[SmartMonitorCoordinator, str, _DescriptionT], Entity],
) -> None:
    """Add entities for every disk, including disks that show up later.

    An entity is added once the disk reports the value it shows, so a disk
    that was asleep at startup gets its entities when it wakes up.
    """
    added: set[tuple[str, str]] = set()

    @callback
    def _add_new_entities() -> None:
        entities = []
        for disk_id, disk in coordinator.data.items():
            for description in descriptions:
                if (disk_id, description.key) in added or not description.exists_fn(
                    disk
                ):
                    continue
                added.add((disk_id, description.key))
                entities.append(entity_factory(coordinator, disk_id, description))
        if entities:
            async_add_entities(entities)

    _add_new_entities()
    coordinator.config_entry.async_on_unload(
        coordinator.async_add_listener(_add_new_entities)
    )
