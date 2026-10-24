"""Tests for the SMART Disk Monitor config flow."""

from unittest.mock import AsyncMock, MagicMock

from aiosmartctl import (
    HostInfo,
    SmartctlAuthenticationError,
    SmartctlCommandError,
    SmartctlConnectionError,
    SmartctlHostKeyError,
    SmartctlNotFoundError,
    SmartctlPermissionError,
)
import pytest

from custom_components.smart_monitor.const import (
    CONF_HOST_KEY,
    CONF_PRIVATE_KEY,
    CONF_SKIP_STANDBY,
    CONF_USE_SUDO,
    DOMAIN,
)
from homeassistant.config_entries import SOURCE_USER
from homeassistant.const import (
    CONF_DEVICES,
    CONF_HOST,
    CONF_PASSWORD,
    CONF_PORT,
    CONF_USERNAME,
)
from homeassistant.core import HomeAssistant
from homeassistant.data_entry_flow import FlowResultType

from .const import (
    ENTRY_DATA,
    FINGERPRINT,
    HOST_KEY,
    OTHER_FINGERPRINT,
    OTHER_HOST_KEY,
    PRIVATE_KEY,
)

from pytest_homeassistant_custom_component.common import MockConfigEntry

USER_INPUT = {
    CONF_HOST: "192.168.1.10",
    CONF_PORT: 22,
    CONF_USERNAME: "root",
    CONF_PASSWORD: "secret",
    CONF_USE_SUDO: False,
}

pytestmark = pytest.mark.usefixtures("mock_setup_entry")


async def test_full_flow(
    hass: HomeAssistant,
    mock_client: MagicMock,
    mock_fetch_host_key: AsyncMock,
) -> None:
    """Test adding a host with a password."""
    result = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": SOURCE_USER}
    )
    assert result["type"] is FlowResultType.FORM
    assert result["step_id"] == "user"

    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], {**USER_INPUT, CONF_PORT: 22.0}
    )
    assert result["type"] is FlowResultType.FORM
    assert result["step_id"] == "confirm_host_key"
    assert result["description_placeholders"] == {
        "host": "192.168.1.10",
        "fingerprint": FINGERPRINT,
    }
    mock_client.assert_not_called()

    result = await hass.config_entries.flow.async_configure(result["flow_id"], {})
    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert result["title"] == "tower"
    assert result["data"] == ENTRY_DATA
    assert result["result"].unique_id == FINGERPRINT
    assert mock_client.call_args.kwargs["known_host_key"] == HOST_KEY


async def test_private_key(
    hass: HomeAssistant,
    mock_client: MagicMock,
    mock_fetch_host_key: AsyncMock,
) -> None:
    """Test adding a host with a private key and sudo."""
    result = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": SOURCE_USER}
    )
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"],
        {
            **USER_INPUT,
            CONF_USERNAME: "monitor",
            CONF_PASSWORD: "",
            CONF_PRIVATE_KEY: PRIVATE_KEY.strip(),
            CONF_USE_SUDO: True,
        },
    )
    result = await hass.config_entries.flow.async_configure(result["flow_id"], {})

    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert result["data"] == {
        CONF_HOST: "192.168.1.10",
        CONF_PORT: 22,
        CONF_USERNAME: "monitor",
        CONF_PRIVATE_KEY: PRIVATE_KEY,
        CONF_USE_SUDO: True,
        CONF_HOST_KEY: HOST_KEY,
    }


@pytest.mark.parametrize(
    ("user_input", "error"),
    [
        ({CONF_PASSWORD: ""}, "missing_credentials"),
        ({CONF_PRIVATE_KEY: "not a key"}, "invalid_private_key"),
    ],
)
async def test_invalid_credentials(
    hass: HomeAssistant,
    mock_client: MagicMock,
    mock_fetch_host_key: AsyncMock,
    user_input: dict[str, str],
    error: str,
) -> None:
    """Test credentials that cannot work are refused before connecting."""
    result = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": SOURCE_USER}
    )
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], {**USER_INPUT, **user_input}
    )
    assert result["type"] is FlowResultType.FORM
    assert result["errors"] == {"base": error}
    mock_fetch_host_key.assert_not_called()

    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], USER_INPUT
    )
    result = await hass.config_entries.flow.async_configure(result["flow_id"], {})
    assert result["type"] is FlowResultType.CREATE_ENTRY


async def test_host_unreachable(
    hass: HomeAssistant,
    mock_client: MagicMock,
    mock_fetch_host_key: AsyncMock,
) -> None:
    """Test a host whose SSH server cannot be reached."""
    mock_fetch_host_key.side_effect = SmartctlConnectionError
    result = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": SOURCE_USER}
    )
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], USER_INPUT
    )
    assert result["type"] is FlowResultType.FORM
    assert result["errors"] == {"base": "cannot_connect"}

    mock_fetch_host_key.side_effect = None
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], USER_INPUT
    )
    result = await hass.config_entries.flow.async_configure(result["flow_id"], {})
    assert result["type"] is FlowResultType.CREATE_ENTRY


@pytest.mark.parametrize(
    ("exception", "error"),
    [
        (SmartctlAuthenticationError, "invalid_auth"),
        (SmartctlHostKeyError, "host_key_changed"),
        (SmartctlNotFoundError, "smartctl_not_found"),
        (SmartctlPermissionError, "sudo_failed"),
        (SmartctlConnectionError, "cannot_connect"),
        (SmartctlCommandError, "unknown"),
        (RuntimeError, "unknown"),
    ],
)
async def test_validation_errors(
    hass: HomeAssistant,
    mock_client: MagicMock,
    mock_session: MagicMock,
    mock_fetch_host_key: AsyncMock,
    exception: type[Exception],
    error: str,
) -> None:
    """Test errors after confirming the host key, and recovering from them."""
    mock_session.get_host_info.side_effect = exception
    result = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": SOURCE_USER}
    )
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], USER_INPUT
    )
    result = await hass.config_entries.flow.async_configure(result["flow_id"], {})
    assert result["type"] is FlowResultType.FORM
    assert result["step_id"] == "user"
    assert result["errors"] == {"base": error}

    mock_session.get_host_info.side_effect = None
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], USER_INPUT
    )
    result = await hass.config_entries.flow.async_configure(result["flow_id"], {})
    assert result["type"] is FlowResultType.CREATE_ENTRY


async def test_title_falls_back_to_host(
    hass: HomeAssistant,
    mock_client: MagicMock,
    mock_session: MagicMock,
    mock_fetch_host_key: AsyncMock,
) -> None:
    """Test the entry is named after the address when there is no hostname."""
    mock_session.get_host_info.return_value = HostInfo(hostname="")
    result = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": SOURCE_USER}
    )
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], USER_INPUT
    )
    result = await hass.config_entries.flow.async_configure(result["flow_id"], {})
    assert result["title"] == "192.168.1.10"


async def test_already_configured(
    hass: HomeAssistant,
    mock_config_entry: MockConfigEntry,
    mock_client: MagicMock,
    mock_fetch_host_key: AsyncMock,
) -> None:
    """Test adding a host whose host key is already configured."""
    mock_config_entry.add_to_hass(hass)
    result = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": SOURCE_USER}
    )
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], {**USER_INPUT, CONF_HOST: "tower.local"}
    )
    result = await hass.config_entries.flow.async_configure(result["flow_id"], {})
    assert result["type"] is FlowResultType.ABORT
    assert result["reason"] == "already_configured"


async def test_reauth(
    hass: HomeAssistant,
    mock_config_entry: MockConfigEntry,
    mock_client: MagicMock,
    mock_fetch_host_key: AsyncMock,
) -> None:
    """Test entering new credentials."""
    mock_config_entry.add_to_hass(hass)
    result = await mock_config_entry.start_reauth_flow(hass)
    assert result["type"] is FlowResultType.FORM
    assert result["step_id"] == "reauth_confirm"
    assert result["description_placeholders"]["fingerprint"] == FINGERPRINT

    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], {CONF_PASSWORD: "new"}
    )
    assert result["type"] is FlowResultType.ABORT
    assert result["reason"] == "reauth_successful"
    assert mock_config_entry.data == {**ENTRY_DATA, CONF_PASSWORD: "new"}


async def test_reauth_host_key_changed(
    hass: HomeAssistant,
    mock_config_entry: MockConfigEntry,
    mock_client: MagicMock,
    mock_fetch_host_key: AsyncMock,
) -> None:
    """Test accepting a new host key."""
    mock_config_entry.add_to_hass(hass)
    mock_fetch_host_key.return_value = OTHER_HOST_KEY
    result = await mock_config_entry.start_reauth_flow(hass)
    assert result["step_id"] == "reauth_host_key_changed"
    assert result["description_placeholders"]["fingerprint"] == OTHER_FINGERPRINT

    # The key shown to the user is pinned, even if the host changes it again.
    mock_fetch_host_key.return_value = HOST_KEY
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], {CONF_PASSWORD: "secret"}
    )
    assert result["reason"] == "reauth_successful"
    assert mock_config_entry.data[CONF_HOST_KEY] == OTHER_HOST_KEY
    assert mock_config_entry.unique_id == OTHER_FINGERPRINT


async def test_reauth_migrates_old_entry(
    hass: HomeAssistant,
    mock_client: MagicMock,
    mock_fetch_host_key: AsyncMock,
) -> None:
    """Test that an entry from version 1.x gets a pinned host key."""
    entry = MockConfigEntry(
        domain=DOMAIN,
        data={
            CONF_HOST: "192.168.1.10",
            CONF_PORT: 22,
            CONF_USERNAME: "root",
            CONF_PASSWORD: "secret",
            "ssh_key": "/config/ssh/id_ed25519",
            "server_type": "unraid",
            "scan_interval": 300,
        },
    )
    entry.add_to_hass(hass)
    result = await entry.start_reauth_flow(hass)
    assert result["step_id"] == "reauth_confirm"

    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], {CONF_PRIVATE_KEY: PRIVATE_KEY}
    )
    assert result["reason"] == "reauth_successful"
    assert entry.unique_id == FINGERPRINT
    assert entry.data == {
        CONF_HOST: "192.168.1.10",
        CONF_PORT: 22,
        CONF_USERNAME: "root",
        CONF_USE_SUDO: False,
        CONF_PRIVATE_KEY: PRIVATE_KEY,
        CONF_HOST_KEY: HOST_KEY,
    }


@pytest.mark.parametrize(
    ("user_input", "exception", "error"),
    [
        ({}, None, "missing_credentials"),
        ({CONF_PASSWORD: "wrong"}, SmartctlAuthenticationError, "invalid_auth"),
        ({CONF_PASSWORD: "secret"}, RuntimeError, "unknown"),
    ],
)
async def test_reauth_errors(
    hass: HomeAssistant,
    mock_config_entry: MockConfigEntry,
    mock_client: MagicMock,
    mock_session: MagicMock,
    mock_fetch_host_key: AsyncMock,
    user_input: dict[str, str],
    exception: type[Exception] | None,
    error: str,
) -> None:
    """Test errors during reauthentication."""
    mock_config_entry.add_to_hass(hass)
    mock_session.get_host_info.side_effect = exception
    result = await mock_config_entry.start_reauth_flow(hass)
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], user_input
    )
    assert result["type"] is FlowResultType.FORM
    assert result["errors"] == {"base": error}

    mock_session.get_host_info.side_effect = None
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], {CONF_PASSWORD: "secret"}
    )
    assert result["reason"] == "reauth_successful"


async def test_reauth_unreachable(
    hass: HomeAssistant,
    mock_config_entry: MockConfigEntry,
    mock_fetch_host_key: AsyncMock,
) -> None:
    """Test reauthentication when the host cannot be reached."""
    mock_config_entry.add_to_hass(hass)
    mock_fetch_host_key.side_effect = SmartctlConnectionError
    result = await mock_config_entry.start_reauth_flow(hass)
    assert result["type"] is FlowResultType.ABORT
    assert result["reason"] == "cannot_connect"


async def test_reconfigure(
    hass: HomeAssistant,
    mock_config_entry: MockConfigEntry,
    mock_client: MagicMock,
    mock_fetch_host_key: AsyncMock,
) -> None:
    """Test changing the address of a host."""
    mock_config_entry.add_to_hass(hass)
    result = await mock_config_entry.start_reconfigure_flow(hass)
    assert result["type"] is FlowResultType.FORM
    assert result["step_id"] == "reconfigure"

    result = await hass.config_entries.flow.async_configure(
        result["flow_id"],
        {
            CONF_HOST: "tower.local",
            CONF_PORT: 2222,
            CONF_USERNAME: "root",
            CONF_USE_SUDO: True,
        },
    )
    assert result["type"] is FlowResultType.ABORT
    assert result["reason"] == "reconfigure_successful"
    assert mock_config_entry.data == {
        **ENTRY_DATA,
        CONF_HOST: "tower.local",
        CONF_PORT: 2222,
        CONF_USE_SUDO: True,
    }


async def test_reconfigure_different_host(
    hass: HomeAssistant,
    mock_config_entry: MockConfigEntry,
    mock_client: MagicMock,
    mock_fetch_host_key: AsyncMock,
) -> None:
    """Test that reconfiguring cannot switch to another host."""
    mock_config_entry.add_to_hass(hass)
    mock_fetch_host_key.return_value = OTHER_HOST_KEY
    result = await mock_config_entry.start_reconfigure_flow(hass)
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"],
        {
            CONF_HOST: "10.0.0.2",
            CONF_PORT: 22,
            CONF_USERNAME: "root",
            CONF_USE_SUDO: False,
        },
    )
    assert result["type"] is FlowResultType.ABORT
    assert result["reason"] == "different_host"


@pytest.mark.parametrize(
    ("fetch_error", "validate_error", "error"),
    [
        (SmartctlConnectionError, None, "cannot_connect"),
        (None, SmartctlPermissionError, "sudo_failed"),
        (None, RuntimeError, "unknown"),
    ],
)
async def test_reconfigure_errors(
    hass: HomeAssistant,
    mock_config_entry: MockConfigEntry,
    mock_client: MagicMock,
    mock_session: MagicMock,
    mock_fetch_host_key: AsyncMock,
    fetch_error: type[Exception] | None,
    validate_error: type[Exception] | None,
    error: str,
) -> None:
    """Test errors while reconfiguring."""
    mock_config_entry.add_to_hass(hass)
    mock_fetch_host_key.side_effect = fetch_error
    mock_session.get_host_info.side_effect = validate_error
    user_input = {
        CONF_HOST: "192.168.1.10",
        CONF_PORT: 22,
        CONF_USERNAME: "monitor",
        CONF_USE_SUDO: True,
    }
    result = await mock_config_entry.start_reconfigure_flow(hass)
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], user_input
    )
    assert result["type"] is FlowResultType.FORM
    assert result["errors"] == {"base": error}

    mock_fetch_host_key.side_effect = None
    mock_session.get_host_info.side_effect = None
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], user_input
    )
    assert result["reason"] == "reconfigure_successful"


async def test_options(
    hass: HomeAssistant,
    mock_config_entry: MockConfigEntry,
) -> None:
    """Test the options flow."""
    mock_config_entry.add_to_hass(hass)
    result = await hass.config_entries.options.async_init(mock_config_entry.entry_id)
    assert result["type"] is FlowResultType.FORM
    assert result["step_id"] == "init"

    result = await hass.config_entries.options.async_configure(
        result["flow_id"],
        {CONF_SKIP_STANDBY: False, CONF_DEVICES: "/dev/sda\n\n/dev/bus/0 megaraid,3\n"},
    )
    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert mock_config_entry.options == {
        CONF_SKIP_STANDBY: False,
        CONF_DEVICES: ["/dev/sda", "/dev/bus/0 megaraid,3"],
    }


async def test_options_invalid_device(
    hass: HomeAssistant,
    mock_config_entry: MockConfigEntry,
) -> None:
    """Test that invalid device specifications are refused."""
    mock_config_entry.add_to_hass(hass)
    result = await hass.config_entries.options.async_init(mock_config_entry.entry_id)
    result = await hass.config_entries.options.async_configure(
        result["flow_id"],
        {CONF_SKIP_STANDBY: True, CONF_DEVICES: "sda; reboot"},
    )
    assert result["type"] is FlowResultType.FORM
    assert result["errors"] == {CONF_DEVICES: "invalid_device"}

    result = await hass.config_entries.options.async_configure(
        result["flow_id"], {CONF_SKIP_STANDBY: True}
    )
    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert mock_config_entry.options == {CONF_SKIP_STANDBY: True, CONF_DEVICES: []}
