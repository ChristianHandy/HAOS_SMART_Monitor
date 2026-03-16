"""SSH client and SMART data fetcher for SMART Disk Monitor."""
from __future__ import annotations

import json
import logging
import re
from dataclasses import dataclass, field
from typing import Any

import paramiko

from .const import SMART_ATTRS, NVME_ATTRS, HEALTH_PASSED, HEALTH_FAILED, HEALTH_UNKNOWN

_LOGGER = logging.getLogger(__name__)


@dataclass
class DiskSmartData:
    """Represents SMART data for a single disk."""
    device: str
    model: str = "Unknown"
    serial: str = "Unknown"
    firmware: str = "Unknown"
    capacity: str = "Unknown"
    rpm: str = "Unknown"
    disk_type: str = "HDD"  # HDD, SSD, NVMe
    health: str = HEALTH_UNKNOWN
    temperature: int | None = None
    power_on_hours: int | None = None
    power_cycles: int | None = None
    reallocated_sectors: int | None = None
    pending_sectors: int | None = None
    uncorrectable_sectors: int | None = None
    smart_attributes: dict[str, Any] = field(default_factory=dict)
    nvme_attributes: dict[str, Any] = field(default_factory=dict)
    raw_output: str = ""
    error: str | None = None
    # Self-test log
    last_test_type: str | None = None       # "Short", "Extended", "Conveyance"
    last_test_result: str | None = None     # "Completed without error", "Failed", …
    last_test_date: str | None = None       # ISO-8601 string or human-readable
    last_test_remaining: int | None = None  # % remaining (0 = done)
    test_log: list[dict[str, Any]] = field(default_factory=list)  # up to 21 entries


class SmartDataFetcher:
    """Fetches SMART data from a remote server via SSH."""

    def __init__(
        self,
        host: str,
        port: int,
        username: str,
        password: str | None = None,
        ssh_key_path: str | None = None,
        server_type: str = "generic_linux",
    ):
        self.host = host
        self.port = port
        self.username = username
        self.password = password
        self.ssh_key_path = ssh_key_path
        self.server_type = server_type
        self._client: paramiko.SSHClient | None = None
        self._smartctl_path: str = "smartctl"  # resolved on first connect

    def connect(self) -> None:
        """Establish SSH connection."""
        self._client = paramiko.SSHClient()
        self._client.set_missing_host_key_policy(paramiko.AutoAddPolicy())

        connect_kwargs: dict[str, Any] = {
            "hostname": self.host,
            "port": self.port,
            "username": self.username,
            "timeout": 15,
            "allow_agent": False,
            "look_for_keys": False,
        }
        if self.ssh_key_path:
            connect_kwargs["key_filename"] = self.ssh_key_path
        elif self.password:
            connect_kwargs["password"] = self.password

        self._client.connect(**connect_kwargs)

    def disconnect(self) -> None:
        """Close SSH connection."""
        if self._client:
            self._client.close()
            self._client = None

    def _exec(self, command: str) -> tuple[str, str]:
        """Execute a command over SSH. Returns (stdout, stderr)."""
        if not self._client:
            raise RuntimeError("SSH client not connected")

        # Do NOT use get_pty() — it merges stderr into stdout and adds
        # terminal escape codes that break JSON parsing.
        # Instead, set environment variables to ensure correct behaviour.
        _, stdout, stderr = self._client.exec_command(
            command,
            timeout=30,
            environment={
                "PATH": "/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin",
                "HOME": "/root",
                "TERM": "dumb",
            },
        )
        out = stdout.read().decode("utf-8", errors="replace")
        err = stderr.read().decode("utf-8", errors="replace")
        exit_code = stdout.channel.recv_exit_status()
        _LOGGER.debug(
            "exec(%r) → exit=%d stdout=%r err=%r",
            command, exit_code, out[:300], err[:300],
        )
        return out, err
        if err.strip():
            _LOGGER.debug("SSH stderr for '%s': %s", command, err.strip())
        return out, err

    def _find_smartctl(self) -> str:
        """Find the full path to smartctl on the remote host."""
        out, _ = self._exec("which smartctl || command -v smartctl || find /usr /sbin /bin -name smartctl 2>/dev/null | head -1")
        path = out.strip().splitlines()[0].strip() if out.strip() else ""
        if path:
            _LOGGER.debug("Found smartctl at: %s", path)
            return path
        # Common locations as fallback
        for p in ("/usr/sbin/smartctl", "/sbin/smartctl", "/usr/bin/smartctl"):
            chk, _ = self._exec(f"test -x {p} && echo yes")
            if chk.strip() == "yes":
                return p
        _LOGGER.warning("smartctl not found on %s — install smartmontools", self.host)
        return "smartctl"  # last resort, let it fail with a clear error

    def list_disks(self) -> list[str]:
        """List block devices on the remote server."""
        try:
            out, _ = self._exec(
                "lsblk -d -o NAME,TYPE --json 2>/dev/null || "
                "lsblk -d -n -o NAME,TYPE 2>/dev/null"
            )
            devices: list[str] = []

            if out.strip().startswith("{"):
                data = json.loads(out)
                for dev in data.get("blockdevices", []):
                    if dev.get("type") in ("disk",):
                        name = dev.get("name", "")
                        if name and not name.startswith("loop"):
                            devices.append(f"/dev/{name}")
            else:
                for line in out.splitlines():
                    parts = line.split()
                    if len(parts) >= 2 and parts[1] == "disk":
                        name = parts[0].strip()
                        if name and not name.startswith("loop"):
                            devices.append(f"/dev/{name}")

            _LOGGER.debug("list_disks on %s: %s", self.host, devices)
            return devices
        except Exception as exc:
            _LOGGER.warning("Failed to list disks on %s: %s", self.host, exc)
            return []

    def get_smart_data(self, device: str) -> DiskSmartData:
        """Fetch and parse SMART data for a single device."""
        disk = DiskSmartData(device=device)
        try:
            smartctl = self._smartctl_path
            json_out, json_err = self._exec(f"{smartctl} -a --json=c {device} 2>&1")
            _LOGGER.warning(
                "smartctl output for %s on %s (first 300): %r err: %r",
                device, self.host, json_out[:300], json_err[:300],
            )
            if json_out.strip().startswith("{"):
                disk = self._parse_smartctl_json(device, json_out)
            else:
                text_out, text_err = self._exec(f"{smartctl} -a {device} 2>&1")
                _LOGGER.warning(
                    "smartctl text fallback for %s: %r err: %r",
                    device, text_out[:300], text_err[:300],
                )
                if text_out.strip():
                    disk = self._parse_smartctl_text(device, text_out)
                else:
                    disk.error = f"No output. stderr: {json_err or text_err}"
                    _LOGGER.error("smartctl no output for %s on %s: %s", device, self.host, disk.error)
        except Exception as exc:
            _LOGGER.error("Error reading SMART data for %s on %s: %s", device, self.host, exc)
            disk.error = str(exc)
        return disk

    def run_test(self, device: str, test_type: str = "short") -> str:
        """Start a SMART self-test on the device."""
        try:
            self.connect()
            self._smartctl_path = self._find_smartctl()
            out, err = self._exec(f"{self._smartctl_path} -t {test_type} {device} 2>&1")
        finally:
            self.disconnect()
        return out or err

    def download_report(self, device: str) -> str:
        """Return the full smartctl -x output as a string for download."""
        try:
            self.connect()
            self._smartctl_path = self._find_smartctl()
            out, err = self._exec(f"{self._smartctl_path} -x {device} 2>&1")
        finally:
            self.disconnect()
        return out or err

    def fetch_all_disks(self) -> dict[str, DiskSmartData]:
        """Connect, fetch all disks, disconnect, return results."""
        results: dict[str, DiskSmartData] = {}
        try:
            self.connect()
            self._smartctl_path = self._find_smartctl()
            _LOGGER.warning("smart_monitor: using smartctl=%s on %s", self._smartctl_path, self.host)
            devices = self.list_disks()
            _LOGGER.warning("smart_monitor: found disks on %s: %s", self.host, devices)
            for dev in devices:
                results[dev] = self.get_smart_data(dev)
        except Exception as exc:
            _LOGGER.error("Failed to fetch SMART data from %s: %s", self.host, exc)
        finally:
            self.disconnect()
        return results

    # ------------------------------------------------------------------
    # JSON parser (smartctl --json)
    # ------------------------------------------------------------------
    def _parse_smartctl_json(self, device: str, raw: str) -> DiskSmartData:
        disk = DiskSmartData(device=device, raw_output=raw)
        try:
            data = json.loads(raw)

            info = data.get("device", {})
            disk.disk_type = self._detect_type_json(data, info)

            model_info = data.get("model_name", "")
            disk.model = model_info or data.get("model_family", "Unknown")
            disk.serial = data.get("serial_number", "Unknown")
            disk.firmware = data.get("firmware_version", "Unknown")

            capacity_bytes = data.get("user_capacity", {}).get("bytes", 0)
            if capacity_bytes:
                disk.capacity = self._format_bytes(capacity_bytes)

            rotation = data.get("rotation_rate", 0)
            if rotation:
                disk.rpm = str(rotation)
                disk.disk_type = "HDD"
            elif rotation == 0:
                disk.disk_type = "SSD" if disk.disk_type != "NVMe" else "NVMe"

            # Health
            smart_status = data.get("smart_status", {})
            if smart_status.get("passed") is True:
                disk.health = HEALTH_PASSED
            elif smart_status.get("passed") is False:
                disk.health = HEALTH_FAILED

            # Temperature
            temp_data = data.get("temperature", {})
            if "current" in temp_data:
                disk.temperature = temp_data["current"]

            # ATA attributes
            ata_attrs = data.get("ata_smart_attributes", {}).get("table", [])
            for attr in ata_attrs:
                attr_id = attr.get("id", 0)
                raw_val = attr.get("raw", {}).get("value", 0)
                name = attr.get("name", f"attr_{attr_id}")
                disk.smart_attributes[attr_id] = {
                    "name": name,
                    "value": attr.get("value", 0),
                    "worst": attr.get("worst", 0),
                    "thresh": attr.get("thresh", 0),
                    "raw": raw_val,
                    "flags": attr.get("flags", {}).get("string", ""),
                }
                if attr_id == 9:
                    disk.power_on_hours = raw_val
                elif attr_id == 12:
                    disk.power_cycles = raw_val
                elif attr_id == 5:
                    disk.reallocated_sectors = raw_val
                elif attr_id == 197:
                    disk.pending_sectors = raw_val
                elif attr_id == 198:
                    disk.uncorrectable_sectors = raw_val
                elif attr_id in (190, 194) and disk.temperature is None:
                    disk.temperature = raw_val

            # NVMe attributes
            nvme_health = data.get("nvme_smart_health_information_log", {})
            if nvme_health:
                disk.disk_type = "NVMe"
                for key, meta in NVME_ATTRS.items():
                    if key in nvme_health:
                        disk.nvme_attributes[key] = {
                            "name": meta["name"],
                            "value": nvme_health[key],
                            "unit": meta["unit"],
                            "icon": meta["icon"],
                        }
                if "temperature" in nvme_health and disk.temperature is None:
                    disk.temperature = nvme_health["temperature"]
                disk.power_on_hours = nvme_health.get("power_on_hours", disk.power_on_hours)
                disk.power_cycles = nvme_health.get("power_cycles", disk.power_cycles)

            # Self-test log (ATA)
            test_table = data.get("ata_smart_self_test_log", {}).get("standard", {}).get("table", [])
            self._apply_test_log_json(disk, test_table)

        except Exception as exc:
            _LOGGER.error("JSON parse error for %s: %s", device, exc)
            disk.error = str(exc)
        return disk

    # ------------------------------------------------------------------
    # Text parser (fallback)
    # ------------------------------------------------------------------
    def _parse_smartctl_text(self, device: str, raw: str) -> DiskSmartData:
        disk = DiskSmartData(device=device, raw_output=raw)
        lines = raw.splitlines()

        for line in lines:
            low = line.lower()
            if "device model:" in low:
                disk.model = line.split(":", 1)[1].strip()
            elif "model number:" in low:
                disk.model = line.split(":", 1)[1].strip()
            elif "serial number:" in low:
                disk.serial = line.split(":", 1)[1].strip()
            elif "firmware version:" in low:
                disk.firmware = line.split(":", 1)[1].strip()
            elif "user capacity:" in low:
                m = re.search(r"[\d,]+ bytes \[(.+?)\]", line)
                if m:
                    disk.capacity = m.group(1).strip()
            elif "rotation rate:" in low:
                val = line.split(":", 1)[1].strip()
                if "solid state" in val.lower():
                    disk.disk_type = "SSD"
                else:
                    disk.rpm = val
                    disk.disk_type = "HDD"
            elif "nvme" in low and "version" in low:
                disk.disk_type = "NVMe"
            elif "smart overall-health" in low or "smart health status" in low:
                if "passed" in low or "ok" in low:
                    disk.health = HEALTH_PASSED
                elif "failed" in low:
                    disk.health = HEALTH_FAILED

        # Parse ATA attribute table
        in_table = False
        for line in lines:
            if "ID#" in line and "ATTRIBUTE_NAME" in line:
                in_table = True
                continue
            if in_table:
                if not line.strip():
                    in_table = False
                    continue
                m = re.match(
                    r"\s*(\d+)\s+(\S+)\s+\S+\s+(\d+)\s+(\d+)\s+(\d+)\s+\S+\s+\S+\s+\S+\s+(\d+)",
                    line,
                )
                if m:
                    attr_id = int(m.group(1))
                    raw_val = int(m.group(6))
                    disk.smart_attributes[attr_id] = {
                        "name": m.group(2),
                        "value": int(m.group(3)),
                        "worst": int(m.group(4)),
                        "thresh": int(m.group(5)),
                        "raw": raw_val,
                    }
                    if attr_id == 9:
                        disk.power_on_hours = raw_val
                    elif attr_id == 12:
                        disk.power_cycles = raw_val
                    elif attr_id == 5:
                        disk.reallocated_sectors = raw_val
                    elif attr_id == 197:
                        disk.pending_sectors = raw_val
                    elif attr_id == 198:
                        disk.uncorrectable_sectors = raw_val
                    elif attr_id in (190, 194):
                        disk.temperature = raw_val

        # Parse self-test log (text)
        self._apply_test_log_text(disk, lines)
        return disk

    # ------------------------------------------------------------------
    # Self-test log parsers
    # ------------------------------------------------------------------
    @staticmethod
    def _apply_test_log_json(disk: "DiskSmartData", table: list) -> None:
        """Parse JSON self-test log table."""
        for entry in table:
            test_type = entry.get("type", {}).get("string", "Unknown")
            status = entry.get("status", {}).get("string", "Unknown")
            lifetime = entry.get("lifetime_hours", 0)
            remaining = entry.get("status", {}).get("remaining_percent", 0)
            disk.test_log.append({
                "type": test_type,
                "result": status,
                "lifetime_hours": lifetime,
                "remaining_percent": remaining,
            })
        if disk.test_log:
            first = disk.test_log[0]
            disk.last_test_type = first["type"]
            disk.last_test_result = first["result"]
            disk.last_test_remaining = first["remaining_percent"]
            # Derive a display date from lifetime hours (approximation)
            disk.last_test_date = f"After {first['lifetime_hours']}h power-on"

    @staticmethod
    def _apply_test_log_text(disk: "DiskSmartData", lines: list[str]) -> None:
        """Parse text self-test log section."""
        import re as _re
        in_log = False
        for line in lines:
            low = line.lower()
            if "self-test log" in low and "num" in low:
                in_log = True
                continue
            if in_log:
                if not line.strip() or line.startswith("SMART"):
                    in_log = False
                    continue
                # Example:  # 1  Short offline   Completed without error  00%  12345  -
                m = _re.match(
                    r"\s*#?\s*\d+\s+(Short|Extended|Conveyance|Short offline|Extended offline)\s+"
                    r"(.+?)\s{2,}(\d+)%\s+(\d+)",
                    line,
                    _re.IGNORECASE,
                )
                if m:
                    disk.test_log.append({
                        "type": m.group(1).strip(),
                        "result": m.group(2).strip(),
                        "remaining_percent": int(m.group(3)),
                        "lifetime_hours": int(m.group(4)),
                    })
        if disk.test_log and disk.last_test_type is None:
            first = disk.test_log[0]
            disk.last_test_type = first["type"]
            disk.last_test_result = first["result"]
            disk.last_test_remaining = first["remaining_percent"]
            disk.last_test_date = f"After {first['lifetime_hours']}h power-on"

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------
    @staticmethod
    def _detect_type_json(data: dict, info: dict) -> str:
        protocol = info.get("protocol", "").upper()
        if "NVME" in protocol:
            return "NVMe"
        if data.get("rotation_rate") == 0:
            return "SSD"
        return "HDD"

    @staticmethod
    def _format_bytes(num: int) -> str:
        for unit in ("B", "KB", "MB", "GB", "TB", "PB"):
            if num < 1000:
                return f"{num:.1f} {unit}"
            num /= 1000
        return f"{num:.1f} EB"
