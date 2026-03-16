"""Button platform for SMART Disk Monitor."""
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
from homeassistant.helpers.update_coordinator import CoordinatorEntity

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

    _LOGGER.debug(
        "smart_monitor button setup_entry called. coordinator.data=%s",
        list(coordinator.data.keys()) if coordinator.data else None,
    )

    def _make_buttons(device: str) -> list[ButtonEntity]:
        _LOGGER.debug("Creating buttons for device %s on %s", device, host)
        return [
            RunTestButton(coordinator, entry, device, host, server_type, "short"),
            RunTestButton(coordinator, entry, device, host, server_type, "long"),
            RunTestButton(coordinator, entry, device, host, server_type, "conveyance"),
            DownloadReportButton(coordinator, entry, device, host, server_type),
        ]

    entities: list[ButtonEntity] = []
    devices = list(coordinator.data.keys()) if coordinator.data else []
    for device in devices:
        entities.extend(_make_buttons(device))

    _LOGGER.debug("smart_monitor: adding %d button entities", len(entities))
    async_add_entities(entities)

    # Dynamically add buttons for disks that appear after the first poll
    _known: set[str] = set(devices)

    def _on_coordinator_update() -> None:
        nonlocal _known
        if not coordinator.data:
            return
        new_devices = set(coordinator.data.keys()) - _known
        if not new_devices:
            return
        _known.update(new_devices)
        new_buttons: list[ButtonEntity] = []
        for dev in new_devices:
            new_buttons.extend(_make_buttons(dev))
        _LOGGER.debug("smart_monitor: dynamically adding %d button entities", len(new_buttons))
        async_add_entities(new_buttons)

    entry.async_on_unload(coordinator.async_add_listener(_on_coordinator_update))


# ---------------------------------------------------------------------------
# Base
# ---------------------------------------------------------------------------

class _DiskButtonBase(CoordinatorEntity[SmartMonitorCoordinator], ButtonEntity):
    """Base button entity."""

    _attr_has_entity_name = True

    def __init__(
        self,
        coordinator: SmartMonitorCoordinator,
        entry: ConfigEntry,
        device: str,
        host: str,
        server_type: str,
    ) -> None:
        super().__init__(coordinator)
        self._entry = entry
        self._device = device
        self._host = host
        self._server_type = server_type
        self._dev_slug = device.replace("/dev/", "").replace("/", "_")

    @property
    def available(self) -> bool:
        return True

    @property
    def device_info(self) -> DeviceInfo:
        # No via_device — stand-alone device entry matching the sensors
        return DeviceInfo(
            identifiers={(DOMAIN, f"{self._host}_{self._dev_slug}")},
            name=f"{self._host} – {self._device}",
            manufacturer=self._server_type.capitalize(),
        )


# ---------------------------------------------------------------------------
# Run Self-Test button
# ---------------------------------------------------------------------------

_TEST_LABELS: dict[str, tuple[str, str]] = {
    "short":      ("Run Short Self-Test",     "mdi:play-circle-outline"),
    "long":       ("Run Long Self-Test",       "mdi:play-circle"),
    "conveyance": ("Run Conveyance Self-Test", "mdi:truck-check"),
}

_TEST_DURATION: dict[str, str] = {
    "short":      "~2 minutes",
    "long":       "hours (varies by disk size)",
    "conveyance": "~5 minutes",
}


class RunTestButton(_DiskButtonBase):
    """Starts a SMART self-test on the disk via SSH."""

    def __init__(self, coordinator, entry, device, host, server_type, test_type: str) -> None:
        super().__init__(coordinator, entry, device, host, server_type)
        self._test_type = test_type
        label, icon = _TEST_LABELS[test_type]
        self._attr_unique_id = f"{host}_{self._dev_slug}_run_{test_type}_test"
        self._attr_name = label
        self._attr_icon = icon

    async def async_press(self) -> None:
        fetcher = self.coordinator.fetcher
        test_type = self._test_type
        hass = self.hass

        _LOGGER.info("Starting %s SMART self-test on %s:%s", test_type, self._host, self._device)

        try:
            output = await hass.async_add_executor_job(
                fetcher.run_test, self._device, test_type
            )
        except Exception as exc:
            _LOGGER.error("Failed to start self-test: %s", exc)
            notify_create(
                hass,
                message=f"Failed to start **{test_type}** self-test on `{self._device}` ({self._host}):\n```\n{exc}\n```",
                title="SMART Self-Test Error",
                notification_id=f"smart_test_error_{self._host}_{self._dev_slug}",
            )
            return

        notify_create(
            hass,
            message=(
                f"**{test_type.capitalize()} self-test** started on "
                f"`{self._device}` ({self._host}).\n\n"
                f"Expected duration: **{_TEST_DURATION[test_type]}**.\n\n"
                f"<details><summary>Raw output</summary>\n\n```\n{output}\n```\n</details>"
            ),
            title="SMART Self-Test Started",
            notification_id=f"smart_test_started_{self._host}_{self._dev_slug}",
        )

        if test_type == "short":
            import asyncio

            async def _delayed_refresh() -> None:
                await asyncio.sleep(130)
                await self.coordinator.async_request_refresh()

            hass.async_create_task(_delayed_refresh())


# ---------------------------------------------------------------------------
# Download Report button
# ---------------------------------------------------------------------------

class DownloadReportButton(_DiskButtonBase):
    """Fetches full smartctl -x report, saves to /config/smart_reports/."""

    _attr_icon = "mdi:download-circle-outline"

    def __init__(self, coordinator, entry, device, host, server_type) -> None:
        super().__init__(coordinator, entry, device, host, server_type)
        self._attr_unique_id = f"{host}_{self._dev_slug}_download_report"
        self._attr_name = "Download SMART Report"

    async def async_press(self) -> None:
        fetcher = self.coordinator.fetcher
        hass = self.hass

        _LOGGER.info("Downloading full SMART report for %s on %s", self._device, self._host)

        try:
            report = await hass.async_add_executor_job(
                fetcher.download_report, self._device
            )
        except Exception as exc:
            _LOGGER.error("Failed to download SMART report: %s", exc)
            notify_create(
                hass,
                message=f"Failed to download SMART report for `{self._device}` ({self._host}):\n```\n{exc}\n```",
                title="SMART Report Error",
                notification_id=f"smart_report_error_{self._host}_{self._dev_slug}",
            )
            return

        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        safe_host = self._host.replace(".", "_").replace(":", "_")
        filename = f"{safe_host}_{self._dev_slug}_{timestamp}.txt"
        filepath = os.path.join(REPORTS_DIR, filename)

        try:
            await hass.async_add_executor_job(_write_report, filepath, report)
            saved_msg = f"Saved to `/config/smart_reports/{filename}`"
        except Exception as exc:
            _LOGGER.warning("Could not save report to disk: %s", exc)
            saved_msg = f"Could not save file: {exc}"

        preview = report[:3000] + ("\n...(truncated)" if len(report) > 3000 else "")

        notify_create(
            hass,
            message=(
                f"**Full SMART Report** for `{self._device}` on `{self._host}`\n\n"
                f"{saved_msg}\n\n"
                f"<details><summary>Report preview</summary>\n\n```\n{preview}\n```\n</details>"
            ),
            title=f"SMART Report: {self._device} @ {self._host}",
            notification_id=f"smart_report_{self._host}_{self._dev_slug}",
        )


def _write_report(filepath: str, content: str) -> None:
    """Synchronous helper — runs in executor."""
    os.makedirs(os.path.dirname(filepath), exist_ok=True)
    with open(filepath, "w", encoding="utf-8") as fh:
        fh.write(content)
