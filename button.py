"""Button platform for SMART Disk Monitor.

Provides per-disk buttons:
  • Run Short Self-Test
  • Run Long (Extended) Self-Test
  • Run Conveyance Self-Test
  • Download Full SMART Report  (fires a persistent notification with the report
    AND saves a .txt file to /config/smart_reports/<host>_<device>_<timestamp>.txt)
"""
from __future__ import annotations

import logging
import os
from datetime import datetime

from homeassistant.components.button import ButtonEntity
from homeassistant.components.persistent_notification import async_create as notify_create
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity import DeviceInfo
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .const import DOMAIN, CONF_HOST, CONF_SERVER_TYPE
from .coordinator import SmartMonitorCoordinator

_LOGGER = logging.getLogger(__name__)

REPORTS_DIR = "/config/smart_reports"


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    coordinator: SmartMonitorCoordinator = hass.data[DOMAIN][entry.entry_id]
    host = entry.data[CONF_HOST]
    server_type = entry.data.get(CONF_SERVER_TYPE, "generic_linux")

    entities: list[ButtonEntity] = []

    # Collect known devices from coordinator data OR fall back to an empty
    # sentinel so that at least a server-level "refresh" button is available.
    # Per-disk buttons are created for every device that was discovered on the
    # first poll.  If the first poll failed the devices will be empty here but
    # a coordinator listener will add new entities once data arrives.
    devices = list(coordinator.data.keys()) if coordinator.data else []

    for device in devices:
        entities.append(RunTestButton(coordinator, entry, device, host, server_type, "short"))
        entities.append(RunTestButton(coordinator, entry, device, host, server_type, "long"))
        entities.append(RunTestButton(coordinator, entry, device, host, server_type, "conveyance"))
        entities.append(DownloadReportButton(coordinator, entry, device, host, server_type))

    async_add_entities(entities)

    # Register a listener: if data arrives late (first poll was slow/failed),
    # add any newly discovered disk buttons dynamically.
    _known: set[str] = set(devices)

    def _check_new_devices() -> None:
        nonlocal _known
        if not coordinator.data:
            return
        new_devices = set(coordinator.data.keys()) - _known
        if not new_devices:
            return
        _known.update(new_devices)
        new_entities: list[ButtonEntity] = []
        for dev in new_devices:
            new_entities.append(RunTestButton(coordinator, entry, dev, host, server_type, "short"))
            new_entities.append(RunTestButton(coordinator, entry, dev, host, server_type, "long"))
            new_entities.append(RunTestButton(coordinator, entry, dev, host, server_type, "conveyance"))
            new_entities.append(DownloadReportButton(coordinator, entry, dev, host, server_type))
        async_add_entities(new_entities)

    coordinator.async_add_listener(_check_new_devices)


# ---------------------------------------------------------------------------
# Base
# ---------------------------------------------------------------------------

class _DiskButtonBase(ButtonEntity):
    _attr_has_entity_name = True

    def __init__(self, coordinator, entry, device, host, server_type):
        self._coordinator = coordinator
        self._entry = entry
        self._device = device
        self._host = host
        self._server_type = server_type
        self._dev_slug = device.replace("/dev/", "").replace("/", "_")

    @property
    def device_info(self) -> DeviceInfo:
        return DeviceInfo(
            identifiers={(DOMAIN, f"{self._host}_{self._dev_slug}")},
            name=f"{self._host} – {self._device}",
        )


# ---------------------------------------------------------------------------
# Run Self-Test button
# ---------------------------------------------------------------------------

_TEST_LABELS = {
    "short":      ("Run Short Self-Test",       "mdi:play-circle-outline"),
    "long":       ("Run Long Self-Test",         "mdi:play-circle"),
    "conveyance": ("Run Conveyance Self-Test",   "mdi:truck-check"),
}

_TEST_DURATION = {
    "short":      "~2 minutes",
    "long":       "hours (varies by disk size)",
    "conveyance": "~5 minutes",
}


class RunTestButton(_DiskButtonBase):
    """Starts a SMART self-test on the disk via SSH."""

    def __init__(self, coordinator, entry, device, host, server_type, test_type: str):
        super().__init__(coordinator, entry, device, host, server_type)
        self._test_type = test_type
        label, icon = _TEST_LABELS[test_type]
        self._attr_unique_id = f"{host}_{self._dev_slug}_run_{test_type}_test"
        self._attr_name = label
        self._attr_icon = icon

    async def async_press(self) -> None:
        """Trigger the SMART self-test."""
        fetcher = self._coordinator.fetcher
        device = self._device
        test_type = self._test_type

        _LOGGER.info(
            "Starting %s SMART self-test on %s:%s", test_type, self._host, device
        )

        try:
            output = await self._coordinator.hass.async_add_executor_job(
                fetcher.run_test, device, test_type
            )
        except Exception as exc:
            _LOGGER.error("Failed to start self-test: %s", exc)
            notify_create(
                self._coordinator.hass,
                message=f"❌ Failed to start {test_type} self-test on **{device}** ({self._host}):\n```\n{exc}\n```",
                title="SMART Self-Test Error",
                notification_id=f"smart_test_error_{self._host}_{self._dev_slug}",
            )
            return

        duration = _TEST_DURATION[test_type]
        notify_create(
            self._coordinator.hass,
            message=(
                f"🔄 **{test_type.capitalize()} self-test** started on "
                f"`{device}` ({self._host}).\n\n"
                f"Expected duration: **{duration}**.\n\n"
                f"<details><summary>Raw output</summary>\n\n```\n{output}\n```\n</details>"
            ),
            title="SMART Self-Test Started",
            notification_id=f"smart_test_started_{self._host}_{self._dev_slug}",
        )

        # Schedule a coordinator refresh after a short test completes (~2 min)
        if test_type == "short":
            import asyncio
            async def _delayed_refresh():
                await asyncio.sleep(130)
                await self._coordinator.async_request_refresh()

            self._coordinator.hass.async_create_task(_delayed_refresh())


# ---------------------------------------------------------------------------
# Download Report button
# ---------------------------------------------------------------------------

class DownloadReportButton(_DiskButtonBase):
    """Downloads the full SMART report and saves it as a file in /config/smart_reports/."""

    _attr_icon = "mdi:download-circle-outline"

    def __init__(self, coordinator, entry, device, host, server_type):
        super().__init__(coordinator, entry, device, host, server_type)
        self._attr_unique_id = f"{host}_{self._dev_slug}_download_report"
        self._attr_name = "Download SMART Report"

    async def async_press(self) -> None:
        """Fetch the full report and write it to disk."""
        fetcher = self._coordinator.fetcher
        device = self._device
        host = self._host
        hass = self._coordinator.hass

        _LOGGER.info("Downloading full SMART report for %s on %s", device, host)

        try:
            report = await hass.async_add_executor_job(fetcher.download_report, device)
        except Exception as exc:
            _LOGGER.error("Failed to download SMART report: %s", exc)
            notify_create(
                hass,
                message=f"❌ Failed to download SMART report for **{device}** ({host}):\n```\n{exc}\n```",
                title="SMART Report Error",
                notification_id=f"smart_report_error_{host}_{self._dev_slug}",
            )
            return

        # Save to /config/smart_reports/
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        safe_dev = self._dev_slug
        safe_host = host.replace(".", "_").replace(":", "_")
        filename = f"{safe_host}_{safe_dev}_{timestamp}.txt"
        filepath = os.path.join(REPORTS_DIR, filename)

        try:
            await hass.async_add_executor_job(_write_report, filepath, report)
            saved_msg = f"📄 Saved to `/config/smart_reports/{filename}`"
        except Exception as exc:
            _LOGGER.warning("Could not save report to disk: %s", exc)
            saved_msg = f"⚠️ Could not save file: {exc}"

        # Show first 3000 chars in notification to avoid HA notification size limits
        preview = report[:3000] + ("\n…(truncated)" if len(report) > 3000 else "")

        notify_create(
            hass,
            message=(
                f"✅ **Full SMART Report** – `{device}` on `{host}`\n\n"
                f"{saved_msg}\n\n"
                f"<details><summary>Report preview</summary>\n\n```\n{preview}\n```\n</details>"
            ),
            title=f"SMART Report: {device} @ {host}",
            notification_id=f"smart_report_{host}_{self._dev_slug}",
        )


def _write_report(filepath: str, content: str) -> None:
    """Synchronous helper to write the report file."""
    os.makedirs(os.path.dirname(filepath), exist_ok=True)
    with open(filepath, "w", encoding="utf-8") as fh:
        fh.write(content)
