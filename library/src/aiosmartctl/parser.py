"""Parsers for smartctl, lsblk and host information output."""

from __future__ import annotations

import json
import re
from collections.abc import Iterable
from typing import Any

from .models import (
    AtaAttribute,
    DeviceSpec,
    Disk,
    DiskType,
    HealthStatus,
    HostInfo,
    Interface,
    SelfTestEntry,
    SelfTestResult,
    SelfTestType,
)

# smartctl exit status bits, see "man smartctl", section RETURN VALUES.
EXIT_COMMAND_LINE = 1 << 0
EXIT_DEVICE_OPEN = 1 << 1
EXIT_SMART_COMMAND = 1 << 2
EXIT_DISK_FAILING = 1 << 3
EXIT_PREFAIL_NOW = 1 << 4

NVME_DATA_UNIT_BYTES = 512_000

_STANDBY_RE = re.compile(r"\bin (STANDBY|SLEEP)\b.*\bmode\b", re.IGNORECASE)

# ATA attributes whose normalized value counts down from 100 as an SSD wears.
_ATA_LIFE_LEFT_ATTRIBUTES = (
    "Percent_Lifetime_Remain",
    "SSD_Life_Left",
    "Media_Wearout_Indicator",
    "Remaining_Lifetime_Perc",
    "Wear_Leveling_Count",
)

_VENDORS = {
    "western digital": "Western Digital",
    "wdc": "Western Digital",
    "seagate": "Seagate",
    "samsung": "Samsung",
    "toshiba": "Toshiba",
    "kioxia": "Kioxia",
    "hgst": "HGST",
    "hitachi": "Hitachi",
    "intel": "Intel",
    "solidigm": "Solidigm",
    "micron": "Micron",
    "crucial": "Crucial",
    "kingston": "Kingston",
    "sandisk": "SanDisk",
    "sk hynix": "SK hynix",
    "hynix": "SK hynix",
    "dell": "Dell",
    "hpe": "HPE",
    "hp": "HP",
    "lenovo": "Lenovo",
    "ibm": "IBM",
    "netapp": "NetApp",
    "corsair": "Corsair",
    "adata": "ADATA",
    "phison": "Phison",
}

_MODEL_NUMBER_VENDORS = (
    (re.compile(r"ST\d", re.IGNORECASE), "Seagate"),
    (re.compile(r"WD[A-Z]?\d", re.IGNORECASE), "Western Digital"),
    (re.compile(r"CT\d", re.IGNORECASE), "Crucial"),
    (re.compile(r"MZ[0-9A-Z]{2}", re.IGNORECASE), "Samsung"),
)


def parse_scan(output: str) -> list[DeviceSpec]:
    """Parse ``smartctl --scan-open`` output in JSON or text form."""
    stripped = output.strip()
    if stripped.startswith("{"):
        data = json.loads(stripped)
        specs = []
        for device in data.get("devices", []):
            if device.get("open_error") or not device.get("name"):
                continue
            specs.append(
                DeviceSpec(path=device["name"], device_type=device.get("type"))
            )
        return _unique(specs)

    specs = []
    for line in stripped.splitlines():
        line = line.split("#", 1)[0].strip()
        if not line:
            continue
        try:
            specs.append(DeviceSpec.parse(line))
        except ValueError:
            continue
    return _unique(specs)


def parse_lsblk(output: str) -> list[DeviceSpec]:
    """Parse ``lsblk -d -J -o NAME,TYPE`` or ``lsblk -d -n -o NAME,TYPE``."""
    stripped = output.strip()
    names: list[str] = []
    if stripped.startswith("{"):
        for device in json.loads(stripped).get("blockdevices", []):
            if device.get("type") == "disk":
                names.append(device.get("name", ""))
    else:
        for line in stripped.splitlines():
            parts = line.split()
            if len(parts) >= 2 and parts[1] == "disk":
                names.append(parts[0])
    return _unique(
        DeviceSpec(path=f"/dev/{name}")
        for name in names
        if name and not name.startswith(("loop", "zram", "ram"))
    )


def parse_host_info(output: str) -> HostInfo:
    """Parse the output of the host information script.

    The script prints ``key=value`` lines; ``/etc/os-release`` lines are
    passed through as-is.
    """
    values: dict[str, str] = {}
    for line in output.splitlines():
        key, sep, value = line.partition("=")
        if sep:
            values.setdefault(key.strip(), value.strip().strip('"'))

    os_name = values.get("NAME")
    os_version = values.get("VERSION_ID") or values.get("VERSION")
    if unraid := values.get("UNRAID_VERSION"):
        os_name, os_version = "Unraid", unraid
    elif pve := values.get("PVE_VERSION"):
        os_name, os_version = "Proxmox VE", pve
    if not os_name:
        os_name = values.get("UNAME_S")

    return HostInfo(
        hostname=values.get("HOSTNAME", ""),
        os_name=os_name or None,
        os_version=os_version or None,
        kernel=values.get("UNAME_R") or None,
        smartctl_version=values.get("SMARTCTL") or None,
    )


def parse_smartctl_version(output: str) -> str | None:
    """Return the version from the first line of ``smartctl --version``."""
    match = re.search(r"smartctl\s+(\d+\.\d+(?:\.\d+)?)", output)
    return match.group(1) if match else None


def parse_smartctl(spec: DeviceSpec, output: str, exit_status: int) -> Disk:
    """Parse ``smartctl -a`` output, preferring JSON."""
    stripped = output.strip()
    if stripped.startswith("{"):
        try:
            data = json.loads(stripped)
        except ValueError:
            pass
        else:
            return parse_smartctl_json(spec, data)
    return parse_smartctl_text(spec, output, exit_status)


def parse_smartctl_json(spec: DeviceSpec, data: dict[str, Any]) -> Disk:
    """Parse ``smartctl --json -a`` output."""
    smartctl = data.get("smartctl", {})
    disk = Disk(
        spec=spec,
        raw=data,
        exit_status=_int(smartctl.get("exit_status")) or 0,
        messages=[
            str(message.get("string", ""))
            for message in smartctl.get("messages", [])
            if message.get("string")
        ],
    )

    if any(_STANDBY_RE.search(message) for message in disk.messages):
        disk.standby = True
        return disk
    if disk.exit_status & (EXIT_COMMAND_LINE | EXIT_DEVICE_OPEN):
        disk.error = _error_message(disk.messages) or (
            f"smartctl exited with status {disk.exit_status}"
        )
        return disk

    protocol = str(data.get("device", {}).get("protocol", "")).upper()
    disk.interface = {
        "ATA": Interface.ATA,
        "NVME": Interface.NVME,
        "SCSI": Interface.SCSI,
    }.get(protocol, Interface.UNKNOWN)

    disk.model = _str(data.get("model_name")) or _str(
        " ".join(filter(None, (data.get("vendor"), data.get("product"))))
    )
    disk.serial = _str(data.get("serial_number"))
    disk.firmware = _str(data.get("firmware_version")) or _str(data.get("revision"))
    disk.wwn = _wwn(data)
    disk.vendor = _vendor(
        _str(data.get("vendor")), _str(data.get("model_family")), disk.model
    )
    disk.capacity_bytes = _int(data.get("user_capacity", {}).get("bytes")) or _int(
        data.get("nvme_total_capacity")
    )
    disk.rotation_rate = _int(data.get("rotation_rate"))
    disk.form_factor = _str(data.get("form_factor", {}).get("name"))

    if disk.interface is Interface.NVME:
        disk.disk_type = DiskType.NVME
    elif disk.rotation_rate == 0:
        disk.disk_type = DiskType.SSD
    elif disk.rotation_rate:
        disk.disk_type = DiskType.HDD

    temperature = data.get("temperature", {})
    disk.temperature = _int(temperature.get("current"))
    disk.temperature_trip = _int(temperature.get("drive_trip"))
    disk.power_on_hours = _int(data.get("power_on_time", {}).get("hours"))
    disk.power_cycles = _int(data.get("power_cycle_count"))

    _apply_ata(disk, data)
    _apply_nvme(disk, data)
    _apply_scsi(disk, data)
    disk.health = _health(disk, data)
    return disk


def parse_smartctl_text(spec: DeviceSpec, output: str, exit_status: int) -> Disk:
    """Parse plain ``smartctl -a`` output from smartctl versions without JSON."""
    disk = Disk(spec=spec, exit_status=exit_status)
    lines = output.splitlines()

    if _STANDBY_RE.search(output):
        disk.standby = True
        return disk
    if exit_status & (EXIT_COMMAND_LINE | EXIT_DEVICE_OPEN):
        disk.error = _error_message(lines) or (
            f"smartctl exited with status {exit_status}"
        )
        return disk

    vendor = product = None
    for line in lines:
        key, sep, value = line.partition(":")
        if not sep:
            continue
        key = key.strip().lower()
        value = value.strip()
        if key in ("device model", "model number"):
            disk.model = value
        elif key == "model family":
            disk.vendor = _vendor(None, value, None)
        elif key == "vendor":
            vendor = value
        elif key == "product":
            product = value
        elif key == "serial number":
            disk.serial = value
        elif key in ("firmware version", "revision"):
            disk.firmware = value
        elif key in ("user capacity", "total nvm capacity"):
            if match := re.match(r"([\d,.\s]+) bytes", value):
                disk.capacity_bytes = int(re.sub(r"\D", "", match.group(1)))
        elif key == "rotation rate":
            if "solid state" in value.lower():
                disk.rotation_rate = 0
            elif match := re.match(r"(\d+)", value):
                disk.rotation_rate = int(match.group(1))
        elif key in ("current drive temperature", "temperature"):
            if match := re.match(r"(\d+)", value):
                disk.temperature = int(match.group(1))
        elif key == "elements in grown defect list":
            disk.grown_defects = _int(value)
        elif "overall-health" in key or key == "smart health status":
            upper = value.upper()
            if "PASSED" in upper or upper == "OK":
                disk.health = HealthStatus.PASSED
            elif "FAIL" in upper:
                disk.health = HealthStatus.FAILED

    if vendor or product:
        disk.model = disk.model or " ".join(filter(None, (vendor, product)))
        disk.interface = Interface.SCSI
    disk.vendor = disk.vendor or _vendor(vendor, None, disk.model)
    if "NVMe" in output and "Model Number" in output:
        disk.interface = Interface.NVME
        disk.disk_type = DiskType.NVME
    elif disk.rotation_rate == 0:
        disk.disk_type = DiskType.SSD
    elif disk.rotation_rate:
        disk.disk_type = DiskType.HDD

    attributes = list(_parse_ata_attribute_table(lines))
    if attributes:
        disk.interface = Interface.ATA
        _apply_ata_attributes(disk, attributes)
    if disk.health is HealthStatus.PASSED and any(
        attribute.failing_now for attribute in attributes
    ):
        disk.health = HealthStatus.WARNING
    if exit_status & EXIT_DISK_FAILING:
        disk.health = HealthStatus.FAILED
    return disk


def deduplicate(disks: Iterable[Disk]) -> list[Disk]:
    """Drop disks seen twice, such as SAS disks reachable over two paths."""
    seen: set[str] = set()
    result = []
    for disk in disks:
        identifier = disk.identifier
        if identifier is not None:
            if identifier in seen:
                continue
            seen.add(identifier)
        result.append(disk)
    return result


# ---------------------------------------------------------------------------
# ATA
# ---------------------------------------------------------------------------


def _apply_ata(disk: Disk, data: dict[str, Any]) -> None:
    table = data.get("ata_smart_attributes", {}).get("table", [])
    attributes = [
        AtaAttribute(
            id=_int(row.get("id")) or 0,
            name=str(row.get("name", "")),
            value=_int(row.get("value")),
            worst=_int(row.get("worst")),
            threshold=_int(row.get("thresh")),
            raw=_int(row.get("raw", {}).get("value")),
            prefailure=bool(row.get("flags", {}).get("prefailure")),
            failing_now=row.get("when_failed") == "now",
        )
        for row in table
    ]
    _apply_ata_attributes(
        disk, attributes, logical_block_size=_int(data.get("logical_block_size"))
    )

    smart_data = data.get("ata_smart_data", {})
    capabilities = smart_data.get("capabilities", {})
    if capabilities.get("self_tests_supported"):
        tests = {SelfTestType.SHORT, SelfTestType.LONG}
        if capabilities.get("conveyance_self_test_supported"):
            tests.add(SelfTestType.CONVEYANCE)
        disk.supported_self_tests = frozenset(tests)

    status = smart_data.get("self_test", {}).get("status", {})
    if (_int(status.get("value")) or 0) >> 4 == 0xF:
        disk.self_test_in_progress = True
        disk.self_test_remaining_percent = _int(status.get("remaining_percent"))

    log = data.get("ata_smart_self_test_log", {}).get("standard", {})
    disk.self_tests = [
        SelfTestEntry(
            test_type=str(row.get("type", {}).get("string", "")),
            status=str(row.get("status", {}).get("string", "")),
            result=_ata_self_test_result(row.get("status", {})),
            lifetime_hours=_int(row.get("lifetime_hours")),
        )
        for row in log.get("table", [])
    ]


def _apply_ata_attributes(
    disk: Disk,
    attributes: list[AtaAttribute],
    *,
    logical_block_size: int | None = None,
) -> None:
    by_name: dict[str, AtaAttribute] = {}
    for attribute in attributes:
        disk.ata_attributes[attribute.id] = attribute
        by_name[attribute.name] = attribute
        raw = attribute.raw
        match attribute.id:
            case 5:
                disk.reallocated_sectors = raw
            case 9 if disk.power_on_hours is None:
                disk.power_on_hours = raw
            case 10:
                disk.spin_retry_count = raw
            case 12 if disk.power_cycles is None:
                disk.power_cycles = raw
            case 187:
                disk.reported_uncorrectable = raw
            case 188:
                disk.command_timeouts = raw
            case 194 | 190 if disk.temperature is None and raw is not None:
                # The upper bytes of the raw value often hold min/max values.
                disk.temperature = raw & 0xFF
            case 196:
                disk.reallocation_events = raw
            case 197:
                disk.pending_sectors = raw
            case 198:
                disk.offline_uncorrectable = raw
            case 199:
                disk.udma_crc_errors = raw

    block_size = logical_block_size or 512
    if (written := by_name.get("Total_LBAs_Written")) and written.raw is not None:
        disk.data_written_bytes = written.raw * block_size
    if (read := by_name.get("Total_LBAs_Read")) and read.raw is not None:
        disk.data_read_bytes = read.raw * block_size

    if disk.disk_type is DiskType.SSD or (
        disk.disk_type is DiskType.UNKNOWN and disk.rotation_rate == 0
    ):
        for name in _ATA_LIFE_LEFT_ATTRIBUTES:
            life_left = by_name.get(name)
            if life_left and life_left.value is not None and life_left.value <= 100:
                disk.percentage_used = 100 - life_left.value
                break


_ATA_ROW_RE = re.compile(
    r"^\s*(?P<id>\d+)\s+(?P<name>\S+)\s+0x[0-9a-fA-F]+\s+(?P<value>\d+)\s+"
    r"(?P<worst>\d+)\s+(?P<thresh>\d+)\s+(?P<type>\S+)\s+\S+\s+"
    r"(?P<when_failed>\S+)\s+(?P<raw>\d+)"
)


def _parse_ata_attribute_table(lines: list[str]) -> Iterable[AtaAttribute]:
    for line in lines:
        if match := _ATA_ROW_RE.match(line):
            yield AtaAttribute(
                id=int(match["id"]),
                name=match["name"],
                value=int(match["value"]),
                worst=int(match["worst"]),
                threshold=int(match["thresh"]),
                raw=int(match["raw"]),
                prefailure=match["type"].lower().startswith("pre"),
                failing_now=match["when_failed"].upper() == "FAILING_NOW",
            )


def _ata_self_test_result(status: dict[str, Any]) -> SelfTestResult:
    value = _int(status.get("value"))
    if value is not None:
        code = value >> 4
        if code == 0:
            return SelfTestResult.PASSED
        if code in (1, 2):
            return SelfTestResult.ABORTED
        if code == 0xF:
            return SelfTestResult.IN_PROGRESS
        if 3 <= code <= 8:
            return SelfTestResult.FAILED
    if status.get("passed") is True:
        return SelfTestResult.PASSED
    if status.get("passed") is False:
        return SelfTestResult.FAILED
    return _result_from_text(str(status.get("string", "")))


# ---------------------------------------------------------------------------
# NVMe
# ---------------------------------------------------------------------------


def _apply_nvme(disk: Disk, data: dict[str, Any]) -> None:
    log = data.get("nvme_smart_health_information_log")
    if not log:
        return
    disk.disk_type = DiskType.NVME
    disk.interface = Interface.NVME
    disk.critical_warning = _int(log.get("critical_warning"))
    if disk.temperature is None:
        disk.temperature = _int(log.get("temperature"))
    disk.available_spare = _int(log.get("available_spare"))
    disk.available_spare_threshold = _int(log.get("available_spare_threshold"))
    disk.percentage_used = _int(log.get("percentage_used"))
    disk.media_errors = _int(log.get("media_errors"))
    disk.unsafe_shutdowns = _int(log.get("unsafe_shutdowns"))
    disk.error_log_entries = _int(log.get("num_err_log_entries"))
    if disk.power_on_hours is None:
        disk.power_on_hours = _int(log.get("power_on_hours"))
    if disk.power_cycles is None:
        disk.power_cycles = _int(log.get("power_cycles"))
    if (units := _int(log.get("data_units_read"))) is not None:
        disk.data_read_bytes = units * NVME_DATA_UNIT_BYTES
    if (units := _int(log.get("data_units_written"))) is not None:
        disk.data_written_bytes = units * NVME_DATA_UNIT_BYTES

    self_test_log = data.get("nvme_self_test_log")
    if self_test_log is None:
        return
    disk.supported_self_tests = frozenset({SelfTestType.SHORT, SelfTestType.LONG})
    if _int(self_test_log.get("current_self_test_operation", {}).get("value")):
        disk.self_test_in_progress = True
        completion = _int(self_test_log.get("current_self_test_completion_percent"))
        if completion is not None:
            disk.self_test_remaining_percent = 100 - completion
    disk.self_tests = [
        SelfTestEntry(
            test_type=str(row.get("self_test_code", {}).get("string", "")),
            status=str(row.get("self_test_result", {}).get("string", "")),
            result=_nvme_self_test_result(row.get("self_test_result", {})),
            lifetime_hours=_int(row.get("power_on_hours")),
        )
        for row in self_test_log.get("table", [])
    ]


def _nvme_self_test_result(result: dict[str, Any]) -> SelfTestResult:
    match _int(result.get("value")):
        case 0:
            return SelfTestResult.PASSED
        case 1 | 2 | 3 | 4 | 8 | 9:
            return SelfTestResult.ABORTED
        case 5 | 6 | 7:
            return SelfTestResult.FAILED
    return _result_from_text(str(result.get("string", "")))


# ---------------------------------------------------------------------------
# SCSI / SAS
# ---------------------------------------------------------------------------


def _apply_scsi(disk: Disk, data: dict[str, Any]) -> None:
    if disk.interface is not Interface.SCSI:
        return
    disk.grown_defects = _int(data.get("scsi_grown_defect_list"))
    if (used := _int(data.get("scsi_percentage_used_endurance_indicator"))) is not None:
        disk.percentage_used = used
    disk.non_medium_errors = _int(
        data.get("scsi_nonmedium_error_count", data.get("scsi_non_medium_error_count"))
    )

    counters = data.get("scsi_error_counter_log", {})
    disk.uncorrected_read_errors = _int(
        counters.get("read", {}).get("total_uncorrected_errors")
    )
    disk.uncorrected_write_errors = _int(
        counters.get("write", {}).get("total_uncorrected_errors")
    )
    disk.uncorrected_verify_errors = _int(
        counters.get("verify", {}).get("total_uncorrected_errors")
    )
    if (
        gigabytes := _float(counters.get("read", {}).get("gigabytes_processed"))
    ) is not None:
        disk.data_read_bytes = round(gigabytes * 1_000_000_000)
    if (
        gigabytes := _float(counters.get("write", {}).get("gigabytes_processed"))
    ) is not None:
        disk.data_written_bytes = round(gigabytes * 1_000_000_000)

    cycles = data.get("scsi_start_stop_cycle_counter", {})
    if disk.power_cycles is None:
        disk.power_cycles = _int(cycles.get("accumulated_start_stop_cycles"))

    disk.supported_self_tests = frozenset({SelfTestType.SHORT, SelfTestType.LONG})
    entries = []
    for index in range(20):
        row = data.get(f"scsi_self_test_{index}")
        if row is None:
            break
        result = row.get("result", {})
        entries.append(
            SelfTestEntry(
                test_type=str(row.get("code", {}).get("string", "")),
                status=str(result.get("string", "")),
                result=_scsi_self_test_result(result),
                lifetime_hours=_int(row.get("power_on_time", {}).get("hours")),
            )
        )
    disk.self_tests = entries
    if entries and entries[0].result is SelfTestResult.IN_PROGRESS:
        disk.self_test_in_progress = True


def _scsi_self_test_result(result: dict[str, Any]) -> SelfTestResult:
    match _int(result.get("value")):
        case 0:
            return SelfTestResult.PASSED
        case 1 | 2:
            return SelfTestResult.ABORTED
        case 3 | 4 | 5 | 6 | 7:
            return SelfTestResult.FAILED
        case 15:
            return SelfTestResult.IN_PROGRESS
    return _result_from_text(str(result.get("string", "")))


# ---------------------------------------------------------------------------
# Shared helpers
# ---------------------------------------------------------------------------


def _health(disk: Disk, data: dict[str, Any]) -> HealthStatus:
    passed = data.get("smart_status", {}).get("passed")
    if passed is False or disk.exit_status & EXIT_DISK_FAILING:
        return HealthStatus.FAILED
    warning = (
        disk.exit_status & EXIT_PREFAIL_NOW
        or any(attribute.failing_now for attribute in disk.ata_attributes.values())
        or bool(disk.critical_warning)
        or (
            disk.available_spare is not None
            and disk.available_spare_threshold is not None
            and disk.available_spare < disk.available_spare_threshold
        )
    )
    if warning:
        return HealthStatus.WARNING
    if passed is True:
        return HealthStatus.PASSED
    return HealthStatus.UNKNOWN


def _result_from_text(text: str) -> SelfTestResult:
    lower = text.lower()
    if "progress" in lower:
        return SelfTestResult.IN_PROGRESS
    if "without error" in lower or lower == "completed":
        return SelfTestResult.PASSED
    if "abort" in lower or "interrupt" in lower:
        return SelfTestResult.ABORTED
    if "fail" in lower or "error" in lower:
        return SelfTestResult.FAILED
    return SelfTestResult.UNKNOWN


def _error_message(messages: Iterable[str]) -> str | None:
    for message in messages:
        if "failed" in message.lower() or "denied" in message.lower():
            return message.strip()
    return None


def _wwn(data: dict[str, Any]) -> str | None:
    wwn = data.get("wwn")
    if isinstance(wwn, dict) and {"naa", "oui", "id"} <= wwn.keys():
        return f"0x{wwn['naa']:x}{wwn['oui']:06x}{wwn['id']:09x}"
    if lu_id := _str(data.get("logical_unit_id")):
        return lu_id.lower()
    return None


def _vendor(
    scsi_vendor: str | None, family: str | None, model: str | None
) -> str | None:
    for candidate in (scsi_vendor, family, model):
        if not candidate:
            continue
        lower = candidate.lower()
        for prefix, name in _VENDORS.items():
            if lower == prefix or lower.startswith(
                (f"{prefix} ", f"{prefix}-", f"{prefix}_")
            ):
                return name
    if model:
        # Bare model numbers such as "ST4000VN008", "WD40EFRX" or "CT1000MX500SSD1".
        for pattern, name in _MODEL_NUMBER_VENDORS:
            if pattern.match(model):
                return name
    return scsi_vendor


def _unique(specs: Iterable[DeviceSpec]) -> list[DeviceSpec]:
    seen: set[str] = set()
    result = []
    for spec in specs:
        if spec.key not in seen:
            seen.add(spec.key)
            result.append(spec)
    return result


def _int(value: Any) -> int | None:
    if isinstance(value, bool):
        return None
    if isinstance(value, int):
        return value
    if isinstance(value, float):
        return int(value)
    if isinstance(value, str):
        digits = value.strip().replace(",", "")
        if digits.isdigit():
            return int(digits)
    return None


def _float(value: Any) -> float | None:
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        return float(value)
    if isinstance(value, str):
        try:
            return float(value.replace(",", ""))
        except ValueError:
            return None
    return None


def _str(value: Any) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    return text or None
