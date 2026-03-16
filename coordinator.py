"""DataUpdateCoordinator for SMART Disk Monitor."""
from __future__ import annotations

import logging
from datetime import timedelta
from typing import Any

from homeassistant.core import HomeAssistant
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed

from .const import DOMAIN, DEFAULT_SCAN_INTERVAL
from .smart_fetcher import SmartDataFetcher, DiskSmartData

_LOGGER = logging.getLogger(__name__)


class SmartMonitorCoordinator(DataUpdateCoordinator[dict[str, dict[str, DiskSmartData]]]):
    """Manages polling SMART data for one or more servers."""

    def __init__(
        self,
        hass: HomeAssistant,
        entry_id: str,
        fetcher: SmartDataFetcher,
        server_name: str,
        scan_interval: int = DEFAULT_SCAN_INTERVAL,
    ) -> None:
        self.fetcher = fetcher
        self.server_name = server_name
        self.entry_id = entry_id

        super().__init__(
            hass,
            _LOGGER,
            name=f"{DOMAIN}_{server_name}",
            update_interval=timedelta(seconds=scan_interval),
        )

    async def _async_update_data(self) -> dict[str, DiskSmartData]:
        """Fetch data from the remote server."""
        try:
            data = await self.hass.async_add_executor_job(self.fetcher.fetch_all_disks)
        except Exception as exc:
            raise UpdateFailed(f"Error fetching SMART data from {self.server_name}: {exc}") from exc

        if not data:
            _LOGGER.warning("No disks found on server %s", self.server_name)

        return data
