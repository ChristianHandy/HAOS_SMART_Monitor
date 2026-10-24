"""Data models for aiosmartctl."""

from __future__ import annotations

import shlex
from dataclasses import dataclass, field
from enum import StrEnum
from typing import Any


class DiskType(StrEnum):
    """Kind of storage medium."""

    HDD = "hdd"
    SSD = "ssd"
    NVME = "nvme"
    UNKNOWN = "unknown"


class Interface(StrEnum):
    """Protocol smartctl used to talk to the disk."""

    ATA = "ata"
    NVME = "nvme"
    SCSI = "scsi"
    UNKNOWN = "unknown"


class HealthStatus(StrEnum):
    """Overall health of a disk."""

    PASSED = "passed"
    WARNING = "warning"
    FAILED = "failed"
    UNKNOWN = "unknown"


class SelfTestType(StrEnum):
    """Self-tests that can be started with ``smartctl -t``."""

    SHORT = "short"
    LONG = "long"
    CONVEYANCE = "conveyance"


class SelfTestResult(StrEnum):
    """Outcome of a self-test log entry."""

    PASSED = "passed"
    FAILED = "failed"
    ABORTED = "aborted"
    IN_PROGRESS = "in_progress"
    UNKNOWN = "unknown"


@dataclass(frozen=True, kw_only=True)
class DeviceSpec:
    """A device path plus the optional ``-d`` type smartctl needs to reach it.

    Disks behind RAID controllers and USB bridges are only reachable with a
    device type, for example ``/dev/bus/0`` with ``megaraid,3`` or
    ``/dev/sg1`` with ``cciss,0``.
    """

    path: str
    device_type: str | None = None

    @property
    def key(self) -> str:
        """Return a string that identifies this spec on its host."""
        if self.device_type:
            return f"{self.path}:{self.device_type}"
        return self.path

    def args(self) -> list[str]:
        """Return the smartctl arguments that select this device."""
        if self.device_type:
            return ["-d", self.device_type, self.path]
        return [self.path]

    @classmethod
    def parse(cls, value: str) -> DeviceSpec:
        """Parse ``/dev/sda``, ``/dev/bus/0 megaraid,3`` or ``/dev/sda -d sat``."""
        parts = shlex.split(value)
        if not parts:
            raise ValueError("Empty device specification")
        if not parts[0].startswith("/"):
            raise ValueError(f"Device path must be absolute: {parts[0]}")
        rest = parts[1:]
        if rest and rest[0] == "-d":
            rest = rest[1:]
            if not rest:
                raise ValueError(f"Missing device type after -d: {value}")
        if len(rest) > 1:
            raise ValueError(f"Unexpected arguments in device specification: {value}")
        device_type = rest[0] if rest else None
        if device_type is not None and not _is_safe_token(device_type):
            raise ValueError(f"Invalid device type: {device_type}")
        return cls(path=parts[0], device_type=device_type)


def _is_safe_token(value: str) -> bool:
    return bool(value) and all(c.isalnum() or c in ",+_-" for c in value)


@dataclass(frozen=True, kw_only=True)
class AtaAttribute:
    """A row from the ATA SMART attribute table."""

    id: int
    name: str
    value: int | None
    worst: int | None
    threshold: int | None
    raw: int | None
    prefailure: bool = False
    failing_now: bool = False


@dataclass(frozen=True, kw_only=True)
class SelfTestEntry:
    """A self-test log entry, newest first."""

    test_type: str
    status: str
    result: SelfTestResult
    lifetime_hours: int | None = None


@dataclass(frozen=True, kw_only=True)
class HostInfo:
    """Information about the host the disks are attached to."""

    hostname: str
    os_name: str | None = None
    os_version: str | None = None
    kernel: str | None = None
    smartctl_version: str | None = None


@dataclass(kw_only=True)
class Disk:
    """SMART information about a single disk.

    Values that the disk does not report are ``None``.
    """

    spec: DeviceSpec
    model: str | None = None
    serial: str | None = None
    wwn: str | None = None
    vendor: str | None = None
    firmware: str | None = None
    capacity_bytes: int | None = None
    rotation_rate: int | None = None
    form_factor: str | None = None
    disk_type: DiskType = DiskType.UNKNOWN
    interface: Interface = Interface.UNKNOWN

    health: HealthStatus = HealthStatus.UNKNOWN
    standby: bool = False
    exit_status: int = 0
    messages: list[str] = field(default_factory=list)
    error: str | None = None

    temperature: int | None = None
    temperature_trip: int | None = None
    power_on_hours: int | None = None
    power_cycles: int | None = None

    # ATA
    reallocated_sectors: int | None = None
    reallocation_events: int | None = None
    pending_sectors: int | None = None
    offline_uncorrectable: int | None = None
    reported_uncorrectable: int | None = None
    command_timeouts: int | None = None
    udma_crc_errors: int | None = None
    spin_retry_count: int | None = None
    ata_attributes: dict[int, AtaAttribute] = field(default_factory=dict)

    # NVMe
    available_spare: int | None = None
    available_spare_threshold: int | None = None
    media_errors: int | None = None
    unsafe_shutdowns: int | None = None
    error_log_entries: int | None = None
    critical_warning: int | None = None

    # SCSI / SAS
    grown_defects: int | None = None
    uncorrected_read_errors: int | None = None
    uncorrected_write_errors: int | None = None
    uncorrected_verify_errors: int | None = None
    non_medium_errors: int | None = None

    # Shared
    percentage_used: int | None = None
    data_read_bytes: int | None = None
    data_written_bytes: int | None = None

    self_tests: list[SelfTestEntry] = field(default_factory=list)
    self_test_in_progress: bool = False
    self_test_remaining_percent: int | None = None
    supported_self_tests: frozenset[SelfTestType] = frozenset()

    raw: dict[str, Any] = field(default_factory=dict, repr=False)

    @property
    def identifier(self) -> str | None:
        """Return an identifier that follows the disk between paths and hosts."""
        if self.wwn:
            return f"wwn-{self.wwn}"
        if self.serial:
            model = (self.model or "disk").strip().replace(" ", "_")
            return f"{model}_{self.serial}".lower()
        return None

    @property
    def last_self_test(self) -> SelfTestEntry | None:
        """Return the newest completed self-test log entry."""
        for entry in self.self_tests:
            if entry.result is not SelfTestResult.IN_PROGRESS:
                return entry
        return None
