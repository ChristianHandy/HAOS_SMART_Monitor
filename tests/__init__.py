"""Tests for the SMART Disk Monitor integration."""

import json
from pathlib import Path

from aiosmartctl import DeviceSpec, Disk
from aiosmartctl.parser import parse_smartctl_json

FIXTURES = Path(__file__).parent / "fixtures"


def load_disk(fixture: str, path: str, device_type: str | None = None) -> Disk:
    """Parse a smartctl JSON fixture."""
    return parse_smartctl_json(
        DeviceSpec(path=path, device_type=device_type),
        json.loads((FIXTURES / fixture).read_text()),
    )


def default_disks() -> list[Disk]:
    """Return a SATA HDD, a SATA SSD, an NVMe SSD and a SAS HDD."""
    return [
        load_disk("ata_hdd.json", "/dev/sda", "sat"),
        load_disk("ata_ssd.json", "/dev/sdb", "sat"),
        load_disk("nvme.json", "/dev/nvme0", "nvme"),
        load_disk("sas_hdd.json", "/dev/bus/0", "megaraid,4"),
    ]
