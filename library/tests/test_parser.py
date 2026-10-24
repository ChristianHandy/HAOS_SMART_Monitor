"""Tests for the smartctl output parsers."""

from __future__ import annotations

import pytest

from aiosmartctl import (
    DeviceSpec,
    DiskType,
    HealthStatus,
    Interface,
    SelfTestResult,
    SelfTestType,
)
from aiosmartctl.parser import (
    deduplicate,
    parse_host_info,
    parse_lsblk,
    parse_scan,
    parse_smartctl,
    parse_smartctl_json,
    parse_smartctl_version,
)

from .conftest import load_fixture, load_json


def test_ata_hdd() -> None:
    """Test a SATA hard disk."""
    disk = parse_smartctl_json(DeviceSpec(path="/dev/sda"), load_json("ata_hdd.json"))
    assert disk.error is None
    assert disk.interface is Interface.ATA
    assert disk.disk_type is DiskType.HDD
    assert disk.model == "WDC WD40EFRX-68N32N0"
    assert disk.vendor == "Western Digital"
    assert disk.serial == "WD-WCC7K1234567"
    assert disk.wwn == "0x50014ee2b619edd5"
    assert disk.identifier == "wwn-0x50014ee2b619edd5"
    assert disk.capacity_bytes == 4000787030016
    assert disk.rotation_rate == 5400
    assert disk.health is HealthStatus.PASSED
    assert disk.temperature == 37
    assert disk.power_on_hours == 35123
    assert disk.power_cycles == 87
    assert disk.reallocated_sectors == 0
    assert disk.pending_sectors == 0
    assert disk.offline_uncorrectable == 0
    assert disk.udma_crc_errors == 2
    assert disk.spin_retry_count == 0
    assert disk.percentage_used is None
    assert disk.supported_self_tests == {
        SelfTestType.SHORT,
        SelfTestType.LONG,
        SelfTestType.CONVEYANCE,
    }
    assert not disk.self_test_in_progress
    assert disk.last_self_test is not None
    assert disk.last_self_test.result is SelfTestResult.PASSED
    assert disk.last_self_test.lifetime_hours == 35100


def test_ata_ssd() -> None:
    """Test a SATA SSD with a running self-test."""
    disk = parse_smartctl_json(DeviceSpec(path="/dev/sdb"), load_json("ata_ssd.json"))
    assert disk.disk_type is DiskType.SSD
    assert disk.vendor == "Samsung"
    assert disk.temperature == 31
    assert disk.percentage_used == 3
    assert disk.data_written_bytes == 39062500000 * 512
    assert disk.reported_uncorrectable == 0
    assert disk.self_test_in_progress
    assert disk.self_test_remaining_percent == 90
    assert disk.supported_self_tests == {SelfTestType.SHORT, SelfTestType.LONG}
    assert disk.last_self_test is None


def test_nvme() -> None:
    """Test an NVMe SSD."""
    disk = parse_smartctl_json(
        DeviceSpec(path="/dev/nvme0", device_type="nvme"), load_json("nvme.json")
    )
    assert disk.interface is Interface.NVME
    assert disk.disk_type is DiskType.NVME
    assert disk.wwn is None
    assert disk.identifier == "samsung_ssd_980_pro_2tb_s69enf0r123456x"
    assert disk.health is HealthStatus.PASSED
    assert disk.temperature == 42
    assert disk.available_spare == 100
    assert disk.percentage_used == 3
    assert disk.media_errors == 0
    assert disk.unsafe_shutdowns == 17
    assert disk.error_log_entries == 4
    assert disk.data_read_bytes == 31253456 * 512_000
    assert disk.data_written_bytes == 45678901 * 512_000
    assert disk.power_on_hours == 6789
    assert disk.supported_self_tests == {SelfTestType.SHORT, SelfTestType.LONG}
    assert [entry.result for entry in disk.self_tests] == [
        SelfTestResult.PASSED,
        SelfTestResult.ABORTED,
    ]


def test_nvme_warning() -> None:
    """Test that NVMe critical warnings and low spare raise a warning."""
    data = load_json("nvme.json")
    data["nvme_smart_health_information_log"]["critical_warning"] = 1
    disk = parse_smartctl_json(DeviceSpec(path="/dev/nvme0"), data)
    assert disk.health is HealthStatus.WARNING

    data = load_json("nvme.json")
    data["nvme_smart_health_information_log"]["available_spare"] = 5
    disk = parse_smartctl_json(DeviceSpec(path="/dev/nvme0"), data)
    assert disk.health is HealthStatus.WARNING


def test_nvme_self_test_running() -> None:
    """Test a running NVMe self-test."""
    data = load_json("nvme.json")
    data["nvme_self_test_log"]["current_self_test_operation"]["value"] = 1
    data["nvme_self_test_log"]["current_self_test_completion_percent"] = 30
    disk = parse_smartctl_json(DeviceSpec(path="/dev/nvme0"), data)
    assert disk.self_test_in_progress
    assert disk.self_test_remaining_percent == 70


def test_sas_hdd() -> None:
    """Test a SAS hard disk."""
    disk = parse_smartctl_json(
        DeviceSpec(path="/dev/sdc", device_type="scsi"), load_json("sas_hdd.json")
    )
    assert disk.interface is Interface.SCSI
    assert disk.disk_type is DiskType.HDD
    assert disk.model == "SEAGATE ST8000NM0075"
    assert disk.vendor == "Seagate"
    assert disk.firmware == "E004"
    assert disk.wwn == "0x5000c500a1b2c3d4"
    assert disk.health is HealthStatus.PASSED
    assert disk.temperature == 34
    assert disk.temperature_trip == 60
    assert disk.power_on_hours == 41234
    assert disk.power_cycles == 61
    assert disk.grown_defects == 3
    assert disk.uncorrected_read_errors == 0
    assert disk.uncorrected_write_errors == 0
    assert disk.uncorrected_verify_errors == 1
    assert disk.non_medium_errors == 5
    assert disk.data_read_bytes == 512_345_678_000_000
    assert disk.data_written_bytes == 123_456_789_000_000
    assert disk.supported_self_tests == {SelfTestType.SHORT, SelfTestType.LONG}
    assert [entry.result for entry in disk.self_tests] == [
        SelfTestResult.PASSED,
        SelfTestResult.ABORTED,
    ]


def test_sas_ssd_endurance() -> None:
    """Test the endurance indicator of a SAS SSD."""
    data = load_json("sas_hdd.json")
    data["rotation_rate"] = 0
    data["scsi_percentage_used_endurance_indicator"] = 12
    disk = parse_smartctl_json(DeviceSpec(path="/dev/sdc"), data)
    assert disk.disk_type is DiskType.SSD
    assert disk.percentage_used == 12


def test_megaraid_sata() -> None:
    """Test a SATA disk behind a MegaRAID controller."""
    spec = DeviceSpec(path="/dev/bus/0", device_type="megaraid,2")
    disk = parse_smartctl_json(spec, load_json("megaraid_sata.json"))
    assert disk.error is None
    assert disk.spec is spec
    assert disk.vendor == "Seagate"
    assert disk.reallocated_sectors == 8
    assert disk.command_timeouts == 4295032833
    assert disk.health is HealthStatus.PASSED


def test_failing_disk() -> None:
    """Test a disk that fails its health check."""
    disk = parse_smartctl_json(
        DeviceSpec(path="/dev/sdd"), load_json("ata_failing.json")
    )
    assert disk.health is HealthStatus.FAILED
    assert disk.reallocated_sectors == 3912
    assert disk.ata_attributes[5].failing_now
    assert disk.last_self_test is not None
    assert disk.last_self_test.result is SelfTestResult.FAILED


def test_prefail_warning() -> None:
    """Test that an attribute at its threshold raises a warning."""
    data = load_json("ata_hdd.json")
    data["ata_smart_attributes"]["table"][1]["when_failed"] = "now"
    disk = parse_smartctl_json(DeviceSpec(path="/dev/sda"), data)
    assert disk.health is HealthStatus.WARNING


def test_unknown_health() -> None:
    """Test a disk without SMART status."""
    data = load_json("ata_hdd.json")
    del data["smart_status"]
    disk = parse_smartctl_json(DeviceSpec(path="/dev/sda"), data)
    assert disk.health is HealthStatus.UNKNOWN


def test_standby() -> None:
    """Test a disk that was not woken up."""
    disk = parse_smartctl_json(DeviceSpec(path="/dev/sde"), load_json("standby.json"))
    assert disk.standby
    assert disk.error is None
    assert disk.identifier is None


def test_open_error() -> None:
    """Test a disk that could not be opened."""
    disk = parse_smartctl_json(
        DeviceSpec(path="/dev/sdf"), load_json("open_error.json")
    )
    assert disk.error == "Smartctl open device: /dev/sdf failed: Permission denied"


def test_open_error_without_message() -> None:
    """Test a failing exit status without a message."""
    disk = parse_smartctl_json(
        DeviceSpec(path="/dev/sdf"), {"smartctl": {"exit_status": 1}}
    )
    assert disk.error == "smartctl exited with status 1"


def test_text_output() -> None:
    """Test output of smartctl versions without JSON support."""
    disk = parse_smartctl(
        DeviceSpec(path="/dev/sda"), load_fixture("ata_hdd_v6.txt"), 0
    )
    assert disk.interface is Interface.ATA
    assert disk.disk_type is DiskType.HDD
    assert disk.model == "WDC WD30EFRX-68EUZN0"
    assert disk.vendor == "Western Digital"
    assert disk.serial == "WD-WMC4N0123456"
    assert disk.firmware == "82.00A82"
    assert disk.capacity_bytes == 3000592982016
    assert disk.health is HealthStatus.PASSED
    assert disk.temperature == 32
    assert disk.power_on_hours == 48210
    assert disk.pending_sectors == 1
    assert disk.udma_crc_errors == 0


def test_text_output_scsi() -> None:
    """Test plain-text output of a SAS disk."""
    output = "\n".join(
        [
            "Vendor:               HGST",
            "Product:              HUH721212AL5200",
            "Revision:             A3D0",
            "User Capacity:        12,000,138,625,024 bytes [12.0 TB]",
            "Rotation Rate:        7200 rpm",
            "Serial number:        8DGABCDE",
            "SMART Health Status: OK",
            "Current Drive Temperature:     36 C",
            "Elements in grown defect list: 0",
        ]
    )
    disk = parse_smartctl(DeviceSpec(path="/dev/sdh"), output, 0)
    assert disk.interface is Interface.SCSI
    assert disk.model == "HGST HUH721212AL5200"
    assert disk.vendor == "HGST"
    assert disk.health is HealthStatus.PASSED
    assert disk.temperature == 36
    assert disk.grown_defects == 0


def test_text_output_failing_and_standby() -> None:
    """Test plain-text failing, warning, standby and error results."""
    failing = parse_smartctl(
        DeviceSpec(path="/dev/sda"),
        "SMART overall-health self-assessment test result: FAILED!\n",
        8,
    )
    assert failing.health is HealthStatus.FAILED

    warning = parse_smartctl(
        DeviceSpec(path="/dev/sda"),
        "SMART overall-health self-assessment test result: PASSED\n"
        "  5 Reallocated_Sector_Ct   0x0033   001   001   140    Pre-fail  Always"
        "   FAILING_NOW 2000\n",
        16,
    )
    assert warning.health is HealthStatus.WARNING

    standby = parse_smartctl(
        DeviceSpec(path="/dev/sda"), "Device is in STANDBY mode, exit(2)\n", 2
    )
    assert standby.standby

    error = parse_smartctl(
        DeviceSpec(path="/dev/sda"),
        "Smartctl open device: /dev/sda failed: No such device\n",
        2,
    )
    assert error.error == "Smartctl open device: /dev/sda failed: No such device"


def test_invalid_json_falls_back_to_text() -> None:
    """Test that broken JSON is parsed as text."""
    disk = parse_smartctl(DeviceSpec(path="/dev/sda"), "{ not json", 0)
    assert disk.health is HealthStatus.UNKNOWN


def test_scan_json() -> None:
    """Test parsing smartctl --scan-open JSON output."""
    assert parse_scan(load_fixture("scan_open.json")) == [
        DeviceSpec(path="/dev/sda", device_type="sat"),
        DeviceSpec(path="/dev/sdc", device_type="scsi"),
        DeviceSpec(path="/dev/bus/0", device_type="megaraid,2"),
        DeviceSpec(path="/dev/nvme0", device_type="nvme"),
    ]


def test_scan_text() -> None:
    """Test parsing smartctl --scan-open text output."""
    assert parse_scan(load_fixture("scan_open.txt")) == [
        DeviceSpec(path="/dev/sda", device_type="sat"),
        DeviceSpec(path="/dev/bus/0", device_type="megaraid,2"),
        DeviceSpec(path="/dev/nvme0", device_type="nvme"),
    ]
    assert parse_scan("garbage line\n") == []


def test_lsblk() -> None:
    """Test parsing lsblk output."""
    expected = [DeviceSpec(path="/dev/sda"), DeviceSpec(path="/dev/nvme0n1")]
    assert parse_lsblk(load_fixture("lsblk.json")) == expected
    assert parse_lsblk("sda disk\nsda1 part\nloop0 loop\nnvme0n1 disk\n") == expected


def test_host_info() -> None:
    """Test parsing host information."""
    info = parse_host_info(
        "HOSTNAME=pve01\nUNAME_S=Linux\nUNAME_R=6.8.12-4-pve\n"
        'PRETTY_NAME="Debian GNU/Linux 12 (bookworm)"\nNAME="Debian GNU/Linux"\n'
        'VERSION_ID="12"\nPVE_VERSION=8.3.0\n'
    )
    assert info.hostname == "pve01"
    assert info.os_name == "Proxmox VE"
    assert info.os_version == "8.3.0"
    assert info.kernel == "6.8.12-4-pve"

    info = parse_host_info('HOSTNAME=tower\nUNAME_S=Linux\nUNRAID_VERSION="7.0.1"\n')
    assert info.os_name == "Unraid"
    assert info.os_version == "7.0.1"

    info = parse_host_info("HOSTNAME=nas\nUNAME_S=FreeBSD\nUNAME_R=14.1-RELEASE\n")
    assert info.os_name == "FreeBSD"
    assert info.os_version is None


def test_smartctl_version() -> None:
    """Test parsing the smartctl version."""
    assert parse_smartctl_version("smartctl 7.4 2023-08-01 r5530") == "7.4"
    assert parse_smartctl_version("smartctl 6.6 2017-11-05 r4594") == "6.6"
    assert parse_smartctl_version("bash: smartctl: not found") is None


def test_deduplicate_multipath() -> None:
    """Test that a SAS disk reachable over two paths is listed once."""
    first = parse_smartctl_json(DeviceSpec(path="/dev/sdc"), load_json("sas_hdd.json"))
    second = parse_smartctl_json(DeviceSpec(path="/dev/sdj"), load_json("sas_hdd.json"))
    standby = parse_smartctl_json(
        DeviceSpec(path="/dev/sde"), load_json("standby.json")
    )
    assert deduplicate([first, second, standby]) == [first, standby]


@pytest.mark.parametrize(
    ("value", "expected"),
    [
        ("/dev/sda", DeviceSpec(path="/dev/sda")),
        (
            "/dev/bus/0 megaraid,3",
            DeviceSpec(path="/dev/bus/0", device_type="megaraid,3"),
        ),
        ("/dev/sg1 -d cciss,0", DeviceSpec(path="/dev/sg1", device_type="cciss,0")),
        (
            "/dev/sdb -d sat+megaraid,1",
            DeviceSpec(path="/dev/sdb", device_type="sat+megaraid,1"),
        ),
    ],
)
def test_device_spec_parse(value: str, expected: DeviceSpec) -> None:
    """Test parsing device specifications."""
    assert DeviceSpec.parse(value) == expected


@pytest.mark.parametrize(
    "value",
    ["", "sda", "/dev/sda megaraid,1 extra", "/dev/sda 'sat;reboot'", "/dev/sda -d"],
)
def test_device_spec_parse_invalid(value: str) -> None:
    """Test that unsafe or malformed device specifications are rejected."""
    with pytest.raises(ValueError):
        DeviceSpec.parse(value)


def test_device_spec_args() -> None:
    """Test the smartctl arguments for a device specification."""
    assert DeviceSpec(path="/dev/sda").args() == ["/dev/sda"]
    spec = DeviceSpec(path="/dev/bus/0", device_type="megaraid,3")
    assert spec.args() == ["-d", "megaraid,3", "/dev/bus/0"]
    assert spec.key == "/dev/bus/0:megaraid,3"
