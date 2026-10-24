"""Tests for SMART Disk Monitor sensors."""

from unittest.mock import MagicMock, patch

from aiosmartctl import DeviceSpec, Disk
from freezegun.api import FrozenDateTimeFactory
import pytest
from syrupy.assertion import SnapshotAssertion

from custom_components.smart_monitor.const import SCAN_INTERVAL
from homeassistant.const import STATE_UNAVAILABLE, STATE_UNKNOWN, Platform
from homeassistant.core import HomeAssistant
from homeassistant.helpers import entity_registry as er

from . import default_disks

from pytest_homeassistant_custom_component.common import (
    MockConfigEntry,
    async_fire_time_changed,
    snapshot_platform,
)


@pytest.mark.usefixtures("entity_registry_enabled_by_default")
async def test_entities(
    hass: HomeAssistant,
    mock_config_entry: MockConfigEntry,
    mock_client: MagicMock,
    entity_registry: er.EntityRegistry,
    snapshot: SnapshotAssertion,
) -> None:
    """Test the sensors of a SATA HDD, a SATA SSD, an NVMe SSD and a SAS HDD."""
    with patch("custom_components.smart_monitor.PLATFORMS", [Platform.SENSOR]):
        mock_config_entry.add_to_hass(hass)
        await hass.config_entries.async_setup(mock_config_entry.entry_id)
        await hass.async_block_till_done()

    await snapshot_platform(hass, entity_registry, snapshot, mock_config_entry.entry_id)


async def test_disk_without_smart(
    hass: HomeAssistant,
    entity_registry: er.EntityRegistry,
    mock_config_entry: MockConfigEntry,
    mock_client: MagicMock,
    mock_session: MagicMock,
) -> None:
    """Test a disk behind a USB bridge without SMART data or serial number."""
    mock_session.get_disks.side_effect = None
    mock_session.get_disks.return_value = [
        Disk(spec=DeviceSpec(path="/dev/sdu"), model="USB Bridge")
    ]
    mock_config_entry.add_to_hass(hass)
    await hass.config_entries.async_setup(mock_config_entry.entry_id)
    await hass.async_block_till_done()

    assert hass.states.get("sensor.usb_bridge_health").state == STATE_UNKNOWN
    entry = entity_registry.async_get("sensor.usb_bridge_health")
    assert entry.unique_id == f"{mock_config_entry.unique_id}_/dev/sdu_health"


async def test_disk_removed(
    hass: HomeAssistant,
    init_integration: MockConfigEntry,
    mock_session: MagicMock,
    freezer: FrozenDateTimeFactory,
) -> None:
    """Test that the entities of a disk that is gone become unavailable."""
    mock_session.get_disks.side_effect = lambda *args, **kwargs: default_disks()[1:]
    freezer.tick(SCAN_INTERVAL)
    async_fire_time_changed(hass)
    await hass.async_block_till_done()

    assert (
        hass.states.get("sensor.wdc_wd40efrx_68n32n0_health").state == STATE_UNAVAILABLE
    )
