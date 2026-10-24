"""Tests for SMART Disk Monitor binary sensors."""

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
    """Test the binary sensors of a SATA HDD, a SATA SSD, an NVMe SSD and a SAS HDD."""
    with patch("custom_components.smart_monitor.PLATFORMS", [Platform.BINARY_SENSOR]):
        mock_config_entry.add_to_hass(hass)
        await hass.config_entries.async_setup(mock_config_entry.entry_id)
        await hass.async_block_till_done()

    await snapshot_platform(hass, entity_registry, snapshot, mock_config_entry.entry_id)


async def test_disk_without_smart(
    hass: HomeAssistant,
    mock_config_entry: MockConfigEntry,
    mock_client: MagicMock,
    mock_session: MagicMock,
) -> None:
    """Test a disk behind a USB bridge that reports no SMART data."""
    mock_session.get_disks.side_effect = None
    mock_session.get_disks.return_value = [
        Disk(spec=DeviceSpec(path="/dev/sdu"), model="USB Bridge", serial="U1")
    ]
    mock_config_entry.add_to_hass(hass)
    await hass.config_entries.async_setup(mock_config_entry.entry_id)
    await hass.async_block_till_done()

    assert (
        hass.states.get("binary_sensor.usb_bridge_health_problem").state
        == STATE_UNKNOWN
    )
    assert hass.states.get("binary_sensor.usb_bridge_bad_sectors") is None


async def test_standby(
    hass: HomeAssistant,
    init_integration: MockConfigEntry,
    mock_session: MagicMock,
    freezer: FrozenDateTimeFactory,
) -> None:
    """Test that a sleeping disk is shown as in standby."""
    disks = default_disks()
    disks[0] = Disk(spec=disks[0].spec, standby=True, wwn=disks[0].wwn)
    mock_session.get_disks.side_effect = None
    mock_session.get_disks.return_value = disks
    freezer.tick(SCAN_INTERVAL)
    async_fire_time_changed(hass)
    await hass.async_block_till_done()

    assert hass.states.get("binary_sensor.wdc_wd40efrx_68n32n0_standby").state == "on"


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
        hass.states.get("binary_sensor.wdc_wd40efrx_68n32n0_health_problem").state
        == STATE_UNAVAILABLE
    )
