"""Tests for setting up SMART Disk Monitor."""

from unittest.mock import MagicMock

from aiosmartctl import (
    DeviceSpec,
    Disk,
    SmartctlAuthenticationError,
    SmartctlConnectionError,
    SmartctlHostKeyError,
)
from freezegun.api import FrozenDateTimeFactory
import pytest

from custom_components.smart_monitor.const import (
    CONF_HOST_KEY,
    CONF_SKIP_STANDBY,
    DOMAIN,
    SCAN_INTERVAL,
)
from homeassistant.config_entries import SOURCE_REAUTH, ConfigEntryState
from homeassistant.const import CONF_DEVICES, STATE_UNAVAILABLE
from homeassistant.core import HomeAssistant
from homeassistant.helpers import device_registry as dr
from homeassistant.setup import async_setup_component

from . import default_disks, load_disk
from .const import ENTRY_DATA, FINGERPRINT

from pytest_homeassistant_custom_component.common import (
    MockConfigEntry,
    async_fire_time_changed,
)
from pytest_homeassistant_custom_component.typing import WebSocketGenerator

HDD_HEALTH = "sensor.wdc_wd40efrx_68n32n0_health"
HDD_TEMPERATURE = "sensor.wdc_wd40efrx_68n32n0_temperature"


async def test_setup_and_unload(
    hass: HomeAssistant,
    init_integration: MockConfigEntry,
    mock_client: MagicMock,
    device_registry: dr.DeviceRegistry,
) -> None:
    """Test setting up and unloading an entry."""
    assert init_integration.state is ConfigEntryState.LOADED
    assert mock_client.call_args.kwargs["known_host_key"] == ENTRY_DATA[CONF_HOST_KEY]

    host = device_registry.async_get_device_by_identifier(
        (DOMAIN, FINGERPRINT), init_integration.entry_id
    )
    assert host is not None
    assert host.name == "tower"
    assert host.model == "Unraid"
    assert host.sw_version == "7.0.1"
    disks = dr.async_entries_for_config_entry(
        device_registry, init_integration.entry_id
    )
    assert len(disks) == 5
    assert all(device.via_device_id == host.id for device in disks if device != host)

    await hass.config_entries.async_unload(init_integration.entry_id)
    assert init_integration.state is ConfigEntryState.NOT_LOADED


@pytest.mark.parametrize(
    ("exception", "state", "reauth"),
    [
        (SmartctlConnectionError, ConfigEntryState.SETUP_RETRY, False),
        (SmartctlAuthenticationError, ConfigEntryState.SETUP_ERROR, True),
        (SmartctlHostKeyError, ConfigEntryState.SETUP_ERROR, True),
    ],
)
@pytest.mark.parametrize("method", ["get_host_info", "get_disks"])
@pytest.mark.usefixtures("mock_fetch_host_key")
async def test_setup_errors(
    hass: HomeAssistant,
    mock_config_entry: MockConfigEntry,
    mock_client: MagicMock,
    mock_session: MagicMock,
    method: str,
    exception: type[Exception],
    state: ConfigEntryState,
    reauth: bool,
) -> None:
    """Test errors while setting up."""
    getattr(mock_session, method).side_effect = exception("boom")
    mock_config_entry.add_to_hass(hass)
    await hass.config_entries.async_setup(mock_config_entry.entry_id)
    await hass.async_block_till_done()

    assert mock_config_entry.state is state
    flows = hass.config_entries.flow.async_progress()
    assert bool(flows) is reauth
    if reauth:
        assert flows[0]["context"]["source"] == SOURCE_REAUTH


@pytest.mark.usefixtures("mock_fetch_host_key")
async def test_missing_host_key_starts_reauth(
    hass: HomeAssistant,
    mock_client: MagicMock,
) -> None:
    """Test that entries without a pinned host key ask for one."""
    entry = MockConfigEntry(domain=DOMAIN, data={**ENTRY_DATA, CONF_HOST_KEY: None})
    entry.add_to_hass(hass)
    await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()

    assert entry.state is ConfigEntryState.SETUP_ERROR
    assert (
        hass.config_entries.flow.async_progress()[0]["context"]["source"]
        == SOURCE_REAUTH
    )
    mock_client.assert_not_called()


async def test_update_failure(
    hass: HomeAssistant,
    init_integration: MockConfigEntry,
    mock_session: MagicMock,
    freezer: FrozenDateTimeFactory,
) -> None:
    """Test that entities become unavailable when the host is unreachable."""
    mock_session.get_disks.side_effect = SmartctlConnectionError("down")
    freezer.tick(SCAN_INTERVAL)
    async_fire_time_changed(hass)
    await hass.async_block_till_done()
    assert hass.states.get(HDD_HEALTH).state == STATE_UNAVAILABLE

    mock_session.get_disks.side_effect = lambda *args, **kwargs: default_disks()
    freezer.tick(SCAN_INTERVAL)
    async_fire_time_changed(hass)
    await hass.async_block_till_done()
    assert hass.states.get(HDD_HEALTH).state == "passed"


@pytest.mark.usefixtures("mock_fetch_host_key")
async def test_update_auth_failure(
    hass: HomeAssistant,
    init_integration: MockConfigEntry,
    mock_session: MagicMock,
    freezer: FrozenDateTimeFactory,
) -> None:
    """Test that a rejected login during polling starts reauthentication."""
    mock_session.get_disks.side_effect = SmartctlAuthenticationError
    freezer.tick(SCAN_INTERVAL)
    async_fire_time_changed(hass)
    await hass.async_block_till_done()

    flows = hass.config_entries.flow.async_progress()
    assert flows[0]["context"]["source"] == SOURCE_REAUTH


async def test_standby_keeps_values(
    hass: HomeAssistant,
    init_integration: MockConfigEntry,
    mock_session: MagicMock,
    freezer: FrozenDateTimeFactory,
) -> None:
    """Test that a sleeping disk keeps its last values."""
    disks = default_disks()
    disks[0] = Disk(spec=disks[0].spec, standby=True, wwn=disks[0].wwn)
    mock_session.get_disks.side_effect = None
    mock_session.get_disks.return_value = disks
    freezer.tick(SCAN_INTERVAL)
    async_fire_time_changed(hass)
    await hass.async_block_till_done()

    assert hass.states.get(HDD_TEMPERATURE).state == "37"
    assert init_integration.runtime_data.data["wwn-0x50014ee2b619edd5"].standby


async def test_unreadable_disk(
    hass: HomeAssistant,
    init_integration: MockConfigEntry,
    mock_session: MagicMock,
    freezer: FrozenDateTimeFactory,
) -> None:
    """Test that a disk that cannot be read becomes unavailable."""
    disks = default_disks()
    disks[0] = Disk(spec=disks[0].spec, error="Permission denied")
    mock_session.get_disks.side_effect = None
    mock_session.get_disks.return_value = disks
    freezer.tick(SCAN_INTERVAL)
    async_fire_time_changed(hass)
    await hass.async_block_till_done()

    assert hass.states.get(HDD_HEALTH).state == STATE_UNAVAILABLE


async def test_new_disk(
    hass: HomeAssistant,
    caplog: pytest.LogCaptureFixture,
    mock_config_entry: MockConfigEntry,
    mock_client: MagicMock,
    mock_session: MagicMock,
    freezer: FrozenDateTimeFactory,
) -> None:
    """Test that disks found later get entities, and unknown sleepers are skipped."""
    hdd = load_disk("ata_hdd.json", "/dev/sda", "sat")
    unknown = Disk(spec=DeviceSpec(path="/dev/sdx"), standby=True)
    broken = Disk(spec=DeviceSpec(path="/dev/sdy"), error="I/O error")
    known_but_broken = Disk(
        spec=DeviceSpec(path="/dev/sdz"), serial="Z1", error="I/O error"
    )
    mock_session.get_disks.side_effect = None
    mock_session.get_disks.return_value = [unknown, broken, known_but_broken]
    mock_config_entry.add_to_hass(hass)
    await hass.config_entries.async_setup(mock_config_entry.entry_id)
    await hass.async_block_till_done()
    assert hass.states.get(HDD_HEALTH) is None
    assert "Cannot read /dev/sdz: I/O error" in caplog.text

    mock_session.get_disks.return_value = [hdd]
    freezer.tick(SCAN_INTERVAL)
    async_fire_time_changed(hass)
    await hass.async_block_till_done()
    assert hass.states.get(HDD_HEALTH).state == "passed"


async def test_options_are_used(
    hass: HomeAssistant,
    mock_client: MagicMock,
    mock_session: MagicMock,
) -> None:
    """Test that manual devices and the standby option reach the library."""
    entry = MockConfigEntry(
        domain=DOMAIN,
        unique_id=FINGERPRINT,
        data=ENTRY_DATA,
        options={CONF_SKIP_STANDBY: False, CONF_DEVICES: ["/dev/sg0 cciss,1"]},
    )
    entry.add_to_hass(hass)
    await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()

    (specs,), kwargs = mock_session.get_disks.call_args
    assert [spec.key for spec in specs] == ["/dev/sg0:cciss,1"]
    assert kwargs == {"skip_standby": False}


async def test_remove_device(
    hass: HomeAssistant,
    init_integration: MockConfigEntry,
    device_registry: dr.DeviceRegistry,
    hass_ws_client: WebSocketGenerator,
) -> None:
    """Test that only disks that are gone can be removed."""
    assert await async_setup_component(hass, "config", {})
    client = await hass_ws_client(hass)
    host = device_registry.async_get_device_by_identifier(
        (DOMAIN, FINGERPRINT), init_integration.entry_id
    )
    disk = device_registry.async_get_device_by_identifier(
        (DOMAIN, "wwn-0x50014ee2b619edd5"), init_integration.entry_id
    )
    gone = device_registry.async_get_or_create(
        config_entry_id=init_integration.entry_id,
        identifiers={(DOMAIN, "wwn-0x5000000000000001")},
    )

    for device, success in ((host, False), (disk, False), (gone, True)):
        await client.send_json_auto_id(
            {
                "type": "config/device_registry/remove_config_entry",
                "config_entry_id": init_integration.entry_id,
                "device_id": device.id,
            }
        )
        response = await client.receive_json()
        assert response["success"] is success
