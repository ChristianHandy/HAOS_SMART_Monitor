"""Fixtures for SMART Disk Monitor tests."""

from collections.abc import AsyncIterator, Generator
from contextlib import asynccontextmanager
from unittest.mock import AsyncMock, MagicMock, PropertyMock, patch

from aiosmartctl import HostInfo
import pytest

from custom_components.smart_monitor.const import DOMAIN
from homeassistant.core import HomeAssistant

from . import default_disks
from .const import ENTRY_DATA, FINGERPRINT, HOST_KEY

from pytest_homeassistant_custom_component.common import MockConfigEntry


# BEGIN CUSTOM-ONLY
@pytest.fixture(autouse=True)
def auto_enable_custom_integrations(
    enable_custom_integrations: None,
) -> None:
    """Enable custom integrations."""


# END CUSTOM-ONLY


# BEGIN CUSTOM-ONLY: Home Assistant core's own conftest provides this fixture.
@pytest.fixture
def entity_registry_enabled_by_default() -> Generator[None]:
    """Enable entities that are disabled by default."""
    with patch(
        "homeassistant.helpers.entity.Entity.entity_registry_enabled_default",
        new_callable=PropertyMock,
        return_value=True,
    ):
        yield


# END CUSTOM-ONLY


@pytest.fixture
def mock_config_entry() -> MockConfigEntry:
    """Return a config entry."""
    return MockConfigEntry(
        domain=DOMAIN,
        title="tower",
        unique_id=FINGERPRINT,
        data=ENTRY_DATA,
    )


@pytest.fixture
def mock_setup_entry() -> Generator[AsyncMock]:
    """Prevent setting up the integration in config flow tests."""
    with patch(
        "custom_components.smart_monitor.async_setup_entry", return_value=True
    ) as mock:
        yield mock


@pytest.fixture
def mock_session() -> MagicMock:
    """Return a smartctl session."""
    session = MagicMock()
    session.host_key = HOST_KEY
    session.get_host_info = AsyncMock(
        return_value=HostInfo(
            hostname="tower",
            os_name="Unraid",
            os_version="7.0.1",
            kernel="6.6.68-Unraid",
            smartctl_version="7.4",
        )
    )
    session.get_disks = AsyncMock(side_effect=lambda *args, **kwargs: default_disks())
    session.start_self_test = AsyncMock(return_value="Testing has begun.")
    session.abort_self_test = AsyncMock()
    return session


@pytest.fixture
def mock_client(mock_session: MagicMock) -> Generator[MagicMock]:
    """Patch the smartctl client."""

    @asynccontextmanager
    async def _session() -> AsyncIterator[MagicMock]:
        yield mock_session

    with patch(
        "custom_components.smart_monitor.SmartctlClient", autospec=True
    ) as client_class:
        client_class.return_value.session.side_effect = _session
        yield client_class


@pytest.fixture
def mock_fetch_host_key() -> Generator[AsyncMock]:
    """Patch fetching the SSH host key."""
    with patch(
        "custom_components.smart_monitor.config_flow.fetch_host_key",
        return_value=HOST_KEY,
    ) as mock:
        yield mock


@pytest.fixture
async def init_integration(
    hass: HomeAssistant,
    mock_config_entry: MockConfigEntry,
    mock_client: MagicMock,
) -> MockConfigEntry:
    """Set up the integration."""
    mock_config_entry.add_to_hass(hass)
    await hass.config_entries.async_setup(mock_config_entry.entry_id)
    await hass.async_block_till_done()
    return mock_config_entry
