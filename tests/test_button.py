"""Tests for the SMART Disk Monitor self-test buttons."""

from unittest.mock import MagicMock, patch

from aiosmartctl import DeviceSpec, SelfTestType, SmartctlCommandError
import pytest
from syrupy.assertion import SnapshotAssertion

from homeassistant.components.button import DOMAIN as BUTTON_DOMAIN, SERVICE_PRESS
from homeassistant.const import ATTR_ENTITY_ID, Platform
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers import entity_registry as er

from pytest_homeassistant_custom_component.common import (
    MockConfigEntry,
    snapshot_platform,
)

HDD = "wdc_wd40efrx_68n32n0"
HDD_SPEC = DeviceSpec(path="/dev/sda", device_type="sat")


async def test_entities(
    hass: HomeAssistant,
    mock_config_entry: MockConfigEntry,
    mock_client: MagicMock,
    entity_registry: er.EntityRegistry,
    snapshot: SnapshotAssertion,
) -> None:
    """Test the self-test buttons of each disk."""
    with patch("custom_components.smart_monitor.PLATFORMS", [Platform.BUTTON]):
        mock_config_entry.add_to_hass(hass)
        await hass.config_entries.async_setup(mock_config_entry.entry_id)
        await hass.async_block_till_done()

    await snapshot_platform(hass, entity_registry, snapshot, mock_config_entry.entry_id)


@pytest.mark.parametrize(
    ("key", "test_type"),
    [
        ("start_short_self_test", SelfTestType.SHORT),
        ("start_long_self_test", SelfTestType.LONG),
        ("start_conveyance_self_test", SelfTestType.CONVEYANCE),
    ],
)
@pytest.mark.usefixtures("init_integration")
async def test_start_self_test(
    hass: HomeAssistant,
    mock_session: MagicMock,
    key: str,
    test_type: SelfTestType,
) -> None:
    """Test starting a self-test."""
    calls = mock_session.get_disks.call_count
    await hass.services.async_call(
        BUTTON_DOMAIN,
        SERVICE_PRESS,
        {ATTR_ENTITY_ID: f"button.{HDD}_{key}"},
        blocking=True,
    )
    mock_session.start_self_test.assert_awaited_once_with(HDD_SPEC, test_type)
    await hass.async_block_till_done()
    assert mock_session.get_disks.call_count == calls + 1


@pytest.mark.usefixtures("init_integration")
async def test_abort_self_test(hass: HomeAssistant, mock_session: MagicMock) -> None:
    """Test aborting a self-test."""
    await hass.services.async_call(
        BUTTON_DOMAIN,
        SERVICE_PRESS,
        {ATTR_ENTITY_ID: f"button.{HDD}_abort_self_test"},
        blocking=True,
    )
    mock_session.abort_self_test.assert_awaited_once_with(HDD_SPEC)


@pytest.mark.usefixtures("init_integration")
async def test_self_test_error(
    hass: HomeAssistant, mock_session: MagicMock, init_integration: MockConfigEntry
) -> None:
    """Test that a failing self-test command raises a translated error."""
    mock_session.start_self_test.side_effect = SmartctlCommandError("busy")
    with pytest.raises(HomeAssistantError) as err:
        await hass.services.async_call(
            BUTTON_DOMAIN,
            SERVICE_PRESS,
            {ATTR_ENTITY_ID: f"button.{HDD}_start_short_self_test"},
            blocking=True,
        )
    assert err.value.translation_key == "self_test_failed"
    assert err.value.translation_placeholders == {
        "device": "/dev/sda:sat",
        "error": "busy",
    }
