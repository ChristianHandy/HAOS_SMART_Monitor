"""Buttons that start and abort SMART self-tests."""

from dataclasses import dataclass
from typing import override

from aiosmartctl import SelfTestType, SmartctlError, SmartctlSession

from homeassistant.components.button import ButtonEntity, ButtonEntityDescription
from homeassistant.const import EntityCategory
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback

from .const import DOMAIN
from .coordinator import SmartMonitorConfigEntry, SmartMonitorCoordinator
from .entity import (
    SmartMonitorEntity,
    SmartMonitorEntityDescription,
    async_setup_disk_entities,
)

PARALLEL_UPDATES = 1


@dataclass(frozen=True, kw_only=True)
class SmartMonitorButtonEntityDescription(
    ButtonEntityDescription, SmartMonitorEntityDescription
):
    """Describes a self-test button."""

    test_type: SelfTestType | None


def _self_test_button(test_type: SelfTestType) -> SmartMonitorButtonEntityDescription:
    return SmartMonitorButtonEntityDescription(
        key=f"self_test_{test_type}",
        translation_key=f"self_test_{test_type}",
        entity_category=EntityCategory.DIAGNOSTIC,
        test_type=test_type,
        exists_fn=lambda disk: test_type in disk.supported_self_tests,
    )


BUTTONS: tuple[SmartMonitorButtonEntityDescription, ...] = (
    _self_test_button(SelfTestType.SHORT),
    _self_test_button(SelfTestType.LONG),
    _self_test_button(SelfTestType.CONVEYANCE),
    SmartMonitorButtonEntityDescription(
        key="abort_self_test",
        translation_key="abort_self_test",
        entity_category=EntityCategory.DIAGNOSTIC,
        test_type=None,
        exists_fn=lambda disk: bool(disk.supported_self_tests),
    ),
)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: SmartMonitorConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    """Set up self-test buttons for all disks."""
    async_setup_disk_entities(
        entry.runtime_data, async_add_entities, BUTTONS, SmartMonitorButtonEntity
    )


class SmartMonitorButtonEntity(SmartMonitorEntity, ButtonEntity):
    """Starts or aborts a self-test on a disk."""

    entity_description: SmartMonitorButtonEntityDescription

    def __init__(
        self,
        coordinator: SmartMonitorCoordinator,
        disk_id: str,
        description: SmartMonitorButtonEntityDescription,
    ) -> None:
        """Initialize the button."""
        super().__init__(coordinator, disk_id, description)

    @override
    async def async_press(self) -> None:
        """Start or abort the self-test."""
        test_type = self.entity_description.test_type
        spec = self.disk.spec
        try:
            async with self.coordinator.client.session() as session:
                await self._run(session, test_type)
        except SmartctlError as err:
            raise HomeAssistantError(
                translation_domain=DOMAIN,
                translation_key="self_test_failed",
                translation_placeholders={"device": spec.key, "error": str(err)},
            ) from err
        await self.coordinator.async_request_refresh()

    async def _run(
        self, session: SmartctlSession, test_type: SelfTestType | None
    ) -> None:
        if test_type is None:
            await session.abort_self_test(self.disk.spec)
        else:
            await session.start_self_test(self.disk.spec, test_type)
