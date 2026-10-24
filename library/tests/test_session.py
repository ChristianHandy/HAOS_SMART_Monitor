"""Tests for running smartctl commands in a session."""

from __future__ import annotations

import pytest

from aiosmartctl import (
    DeviceSpec,
    SelfTestType,
    SmartctlCommandError,
    SmartctlNotFoundError,
    SmartctlPermissionError,
    SmartctlSession,
)

from .conftest import FakeHost, load_fixture, smartctl


async def test_discover_and_read(host: FakeHost) -> None:
    """Test discovering disks and reading all of them."""
    host.respond(smartctl("--scan-open"), load_fixture("scan_open.json"))
    host.respond(smartctl("/dev/sda"), load_fixture("ata_hdd.json"))
    host.respond(smartctl("/dev/sdc"), load_fixture("sas_hdd.json"))
    host.respond(
        smartctl("megaraid,2"), load_fixture("megaraid_sata.json"), exit_status=4
    )
    host.respond(smartctl("/dev/nvme0"), load_fixture("nvme.json"))
    session = SmartctlSession(host)

    disks = await session.get_disks()

    assert [disk.spec.key for disk in disks] == [
        "/dev/sda:sat",
        "/dev/sdc:scsi",
        "/dev/bus/0:megaraid,2",
        "/dev/nvme0:nvme",
    ]
    assert session.smartctl_version == "7.4"
    assert [
        "smartctl",
        "--json=c",
        "-a",
        "-n",
        "standby",
        "-d",
        "megaraid,2",
        "/dev/bus/0",
    ] in host.commands


async def test_wakes_disks_when_asked(host: FakeHost) -> None:
    """Test that standby detection can be turned off."""
    host.respond(smartctl("/dev/sda"), load_fixture("ata_hdd.json"))
    session = SmartctlSession(host)

    await session.get_disk(DeviceSpec(path="/dev/sda"), skip_standby=False)

    assert host.commands[-1] == ["smartctl", "--json=c", "-a", "/dev/sda"]


async def test_sudo(host: FakeHost) -> None:
    """Test that smartctl runs through sudo when enabled."""
    host.respond(
        lambda argv: argv[:2] == ["sudo", "-n"] and "--version" in argv,
        "smartctl 7.4 2023-08-01\n",
    )
    session = SmartctlSession(host, use_sudo=True)

    assert await session.check_smartctl() == "7.4"
    assert host.commands[-1] == ["sudo", "-n", "smartctl", "--version"]


async def test_sudo_needs_password(host: FakeHost) -> None:
    """Test that a sudo password prompt is reported as a permission error."""
    host.respond(
        lambda argv: argv[0] == "sudo",
        exit_status=1,
        stderr="sudo: a password is required\n",
    )
    session = SmartctlSession(host, use_sudo=True)

    with pytest.raises(SmartctlPermissionError, match="password is required"):
        await session.check_smartctl()


async def test_sudo_missing(host: FakeHost) -> None:
    """Test that a missing sudo is reported as a permission error."""
    host.respond(
        lambda argv: argv[0] == "sudo",
        exit_status=127,
        stderr="sh: 1: exec: sudo: not found",
    )
    session = SmartctlSession(host, use_sudo=True)

    with pytest.raises(SmartctlPermissionError, match="sudo is not available"):
        await session.check_smartctl()


async def test_sudo_smartctl_missing(host: FakeHost) -> None:
    """Test that sudo reporting a missing smartctl is reported as not found."""
    host.respond(
        lambda argv: argv[0] == "sudo",
        exit_status=1,
        stderr="sudo: smartctl: command not found",
    )
    session = SmartctlSession(host, use_sudo=True)

    with pytest.raises(SmartctlNotFoundError):
        await session.check_smartctl()


async def test_smartctl_missing() -> None:
    """Test a host without smartmontools."""
    session = SmartctlSession(FakeHost())

    with pytest.raises(SmartctlNotFoundError):
        await session.check_smartctl()


async def test_unexpected_version_output(host: FakeHost) -> None:
    """Test unexpected output from smartctl --version."""
    host.respond(smartctl("--version"), "something else\n")
    session = SmartctlSession(host)

    with pytest.raises(SmartctlCommandError):
        await session.check_smartctl()


async def test_old_smartctl_uses_text(host: FakeHost) -> None:
    """Test that smartctl 6 is used without JSON."""
    host.respond(smartctl("--version"), "smartctl 6.6 2017-11-05 r4594\n")
    host.respond(smartctl("--scan-open"), load_fixture("scan_open.txt"))
    host.respond(smartctl("/dev/sda"), load_fixture("ata_hdd_v6.txt"))
    session = SmartctlSession(host)

    disk = await session.get_disk(DeviceSpec(path="/dev/sda"))
    specs = await session.discover()

    assert not session.supports_json
    assert disk.model == "WDC WD30EFRX-68EUZN0"
    assert ["smartctl", "-a", "-n", "standby", "/dev/sda"] in host.commands
    assert ["smartctl", "--scan-open"] in host.commands
    assert len(specs) == 3


async def test_discover_falls_back_to_lsblk(host: FakeHost) -> None:
    """Test that lsblk is used when smartctl --scan-open finds nothing."""
    host.respond(smartctl("--scan-open"), '{"devices": []}')
    host.respond(
        lambda argv: argv[0] == "<script>" and "lsblk" in argv[1],
        load_fixture("lsblk.json"),
    )
    session = SmartctlSession(host)

    specs = await session.discover()

    assert [spec.path for spec in specs] == ["/dev/sda", "/dev/nvme0n1"]


async def test_permission_denied_hint(host: FakeHost) -> None:
    """Test that permission errors carry a hint."""
    host.respond(smartctl("/dev/sdf"), load_fixture("open_error.json"), exit_status=2)
    session = SmartctlSession(host)

    disk = await session.get_disk(DeviceSpec(path="/dev/sdf"))

    assert disk.error is not None
    assert "enable sudo" in disk.error


async def test_host_info(host: FakeHost) -> None:
    """Test reading host information."""
    host.respond(
        lambda argv: argv[0] == "<script>" and "os-release" in argv[1],
        'HOSTNAME=tower\nUNAME_S=Linux\nUNAME_R=6.6.68-Unraid\nUNRAID_VERSION="7.0.1"\n',
    )
    session = SmartctlSession(host)

    info = await session.get_host_info()

    assert info.hostname == "tower"
    assert info.os_name == "Unraid"
    assert info.smartctl_version == "7.4"


async def test_self_tests(host: FakeHost) -> None:
    """Test starting and aborting self-tests."""
    host.respond(smartctl("-t"), "Testing has begun.\n")
    host.respond(smartctl("-X"), "Self-testing aborted!\n")
    session = SmartctlSession(host)
    spec = DeviceSpec(path="/dev/bus/0", device_type="megaraid,2")

    assert "begun" in await session.start_self_test(spec, SelfTestType.LONG)
    await session.abort_self_test(spec)

    assert ["smartctl", "-t", "long", "-d", "megaraid,2", "/dev/bus/0"] in host.commands
    assert ["smartctl", "-X", "-d", "megaraid,2", "/dev/bus/0"] in host.commands


async def test_self_test_errors(host: FakeHost) -> None:
    """Test failures to start or abort self-tests."""
    host.respond(
        smartctl("-t"),
        "Smartctl open device: /dev/sdz failed: No such device\n",
        exit_status=2,
    )
    host.respond(smartctl("-X"), "", exit_status=2, stderr="open failed")
    session = SmartctlSession(host)
    spec = DeviceSpec(path="/dev/sdz")

    with pytest.raises(SmartctlCommandError, match="No such device"):
        await session.start_self_test(spec)
    with pytest.raises(SmartctlCommandError, match="open failed"):
        await session.abort_self_test(spec)


async def test_commands_are_quoted(host: FakeHost) -> None:
    """Test that device paths cannot inject shell commands."""
    host.respond(smartctl("-a"), load_fixture("ata_hdd.json"))
    session = SmartctlSession(host)
    await session.get_disk(DeviceSpec(path="/dev/sda; reboot"))

    assert host.commands[-1][-1] == "/dev/sda; reboot"
