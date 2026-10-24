"""Run smartctl on a remote host over SSH."""

from __future__ import annotations

import asyncio
import logging
import shlex
from collections.abc import AsyncIterator, Awaitable, Callable, Sequence
from contextlib import asynccontextmanager
from dataclasses import dataclass

import asyncssh

from .exceptions import (
    SmartctlAuthenticationError,
    SmartctlCommandError,
    SmartctlConnectionError,
    SmartctlHostKeyError,
    SmartctlNotFoundError,
    SmartctlPermissionError,
)
from .models import DeviceSpec, Disk, HostInfo, SelfTestType
from .parser import (
    EXIT_COMMAND_LINE,
    EXIT_DEVICE_OPEN,
    deduplicate,
    parse_host_info,
    parse_lsblk,
    parse_scan,
    parse_smartctl,
    parse_smartctl_version,
)

_LOGGER = logging.getLogger(__name__)

# Many NAS distributions keep smartctl in an sbin directory that is not on the
# PATH of non-interactive SSH sessions.
_EXTRA_PATH = "/usr/local/sbin:/usr/local/bin:/usr/sbin:/sbin"

_HOST_INFO_SCRIPT = """
echo "HOSTNAME=$(hostname 2>/dev/null || uname -n)"
echo "UNAME_S=$(uname -s)"
echo "UNAME_R=$(uname -r)"
cat /etc/os-release 2>/dev/null
[ -r /etc/unraid-version ] && sed -n 's/^version=/UNRAID_VERSION=/p' /etc/unraid-version
command -v pveversion >/dev/null 2>&1 && echo "PVE_VERSION=$(pveversion | cut -d/ -f2)"
true
"""


@dataclass(frozen=True, kw_only=True)
class CommandResult:
    """Result of a command run on the host."""

    exit_status: int
    stdout: str
    stderr: str


type CommandRunner = Callable[[str], Awaitable[CommandResult]]


def host_key_fingerprint(host_key: str) -> str:
    """Return the SHA256 fingerprint of an OpenSSH formatted public key."""
    try:
        return asyncssh.import_public_key(host_key).get_fingerprint("sha256")
    except (asyncssh.KeyImportError, ValueError) as err:
        raise ValueError(f"Invalid host key: {err}") from err


def validate_private_key(private_key: str, passphrase: str | None = None) -> None:
    """Raise ValueError when the private key cannot be loaded."""
    try:
        asyncssh.import_private_key(private_key, passphrase)
    except (asyncssh.KeyImportError, ValueError) as err:
        raise ValueError(str(err)) from err


async def fetch_host_key(host: str, port: int = 22, timeout: float = 15) -> str:
    """Return the host key a server presents, in OpenSSH format.

    The key is not verified. Show its fingerprint to the user before trusting
    it, and pass it as ``known_host_key`` from then on.
    """
    try:
        async with asyncio.timeout(timeout):
            key = await asyncssh.get_server_host_key(host, port, config=None)
    except (OSError, TimeoutError, asyncssh.Error) as err:
        raise SmartctlConnectionError(
            f"Cannot connect to {host}:{port}: {err}"
        ) from err
    if key is None:
        raise SmartctlConnectionError(f"{host}:{port} did not present a host key")
    return key.export_public_key("openssh").decode().strip()


class SmartctlClient:
    """Connection settings for a host whose disks are read with smartctl."""

    def __init__(
        self,
        host: str,
        *,
        username: str,
        port: int = 22,
        password: str | None = None,
        private_key: str | None = None,
        private_key_passphrase: str | None = None,
        known_host_key: str | None,
        use_sudo: bool = False,
        connect_timeout: float = 15,
        command_timeout: float = 120,
        max_parallel: int = 4,
    ) -> None:
        """Initialize the client.

        ``known_host_key`` is the OpenSSH public key the host must present.
        Passing ``None`` disables host key verification; only do that to
        fetch a key the user then confirms.
        """
        self.host = host
        self.port = port
        self.username = username
        self._password = password
        self._private_key = private_key
        self._private_key_passphrase = private_key_passphrase
        self.known_host_key = known_host_key
        self.use_sudo = use_sudo
        self.connect_timeout = connect_timeout
        self.command_timeout = command_timeout
        self.max_parallel = max_parallel

    @asynccontextmanager
    async def session(self) -> AsyncIterator[SmartctlSession]:
        """Open an SSH connection and yield a session that uses it."""
        client_keys = None
        if self._private_key:
            try:
                client_keys = [
                    asyncssh.import_private_key(
                        self._private_key, self._private_key_passphrase
                    )
                ]
            except (asyncssh.KeyImportError, ValueError) as err:
                raise SmartctlAuthenticationError(
                    f"Invalid private key: {err}"
                ) from err

        known_hosts: (
            tuple[list[asyncssh.SSHKey], list[asyncssh.SSHKey], list[asyncssh.SSHKey]]
            | None
        ) = None
        if self.known_host_key:
            known_hosts = ([asyncssh.import_public_key(self.known_host_key)], [], [])

        try:
            connection = await asyncssh.connect(
                self.host,
                port=self.port,
                username=self.username,
                password=self._password or None,
                client_keys=client_keys,
                known_hosts=known_hosts,
                agent_path=None,
                config=None,
                connect_timeout=self.connect_timeout,
                keepalive_interval=30,
            )
        except asyncssh.HostKeyNotVerifiable as err:
            raise SmartctlHostKeyError(
                f"{self.host} presented an unexpected host key"
            ) from err
        except asyncssh.PermissionDenied as err:
            raise SmartctlAuthenticationError(
                f"Authentication as {self.username} on {self.host} failed"
            ) from err
        except (OSError, TimeoutError, asyncssh.Error) as err:
            raise SmartctlConnectionError(
                f"Cannot connect to {self.host}:{self.port}: {err}"
            ) from err

        async def run(command: str) -> CommandResult:
            try:
                result = await asyncio.wait_for(
                    connection.run(command, check=False),
                    self.command_timeout,
                )
            except TimeoutError as err:
                raise SmartctlConnectionError(
                    f"Command timed out on {self.host}: {command}"
                ) from err
            except (OSError, asyncssh.Error) as err:
                raise SmartctlConnectionError(
                    f"Lost connection to {self.host}: {err}"
                ) from err
            return CommandResult(
                exit_status=result.exit_status or 0,
                stdout=_text(result.stdout),
                stderr=_text(result.stderr),
            )

        server_key = connection.get_server_host_key()
        try:
            yield SmartctlSession(
                run,
                use_sudo=self.use_sudo,
                max_parallel=self.max_parallel,
                host_key=(
                    server_key.export_public_key("openssh").decode().strip()
                    if server_key
                    else None
                ),
            )
        finally:
            connection.close()
            await connection.wait_closed()


class SmartctlSession:
    """Runs smartctl commands through a command runner."""

    def __init__(
        self,
        runner: CommandRunner,
        *,
        use_sudo: bool = False,
        max_parallel: int = 4,
        host_key: str | None = None,
    ) -> None:
        """Initialize the session."""
        self._runner = runner
        self._use_sudo = use_sudo
        self._semaphore = asyncio.Semaphore(max_parallel)
        self.host_key = host_key
        self.smartctl_version: str | None = None

    async def _shell(self, script: str) -> CommandResult:
        """Run a POSIX shell script, whatever the user's login shell is."""
        return await self._runner(f"sh -c {shlex.quote(script)}")

    async def _smartctl(self, args: Sequence[str]) -> CommandResult:
        argv = ["smartctl", *args]
        if self._use_sudo:
            argv = ["sudo", "-n", *argv]
        script = (
            f'PATH="$PATH:{_EXTRA_PATH}" LC_ALL=C; export PATH LC_ALL; '
            f"exec {shlex.join(argv)}"
        )
        async with self._semaphore:
            result = await self._shell(script)
        _LOGGER.debug(
            "%s exited with %s: %s", shlex.join(argv), result.exit_status, result.stderr
        )
        stderr = result.stderr.strip()
        if self._use_sudo and not result.stdout and "sudo" in stderr:
            if result.exit_status in (126, 127):
                raise SmartctlPermissionError(f"sudo is not available: {stderr}")
            if stderr.startswith("sudo:") and "command not found" not in stderr:
                raise SmartctlPermissionError(stderr)
        if result.exit_status in (126, 127) or (
            not result.stdout and "command not found" in stderr
        ):
            raise SmartctlNotFoundError(
                "smartctl was not found; install smartmontools on the host"
            )
        return result

    async def get_host_info(self) -> HostInfo:
        """Return information about the host."""
        result = await self._shell(_HOST_INFO_SCRIPT)
        info = parse_host_info(result.stdout)
        if self.smartctl_version is None:
            await self.check_smartctl()
        return HostInfo(
            hostname=info.hostname,
            os_name=info.os_name,
            os_version=info.os_version,
            kernel=info.kernel,
            smartctl_version=self.smartctl_version,
        )

    async def check_smartctl(self) -> str:
        """Make sure smartctl can be run and return its version."""
        result = await self._smartctl(["--version"])
        version = parse_smartctl_version(result.stdout)
        if version is None:
            raise SmartctlCommandError(
                f"Unexpected output from smartctl --version: {result.stdout[:200]}"
            )
        self.smartctl_version = version
        return version

    @property
    def supports_json(self) -> bool:
        """Return whether smartctl is new enough for JSON output (7.0)."""
        if self.smartctl_version is None:
            return True
        return int(self.smartctl_version.split(".", 1)[0]) >= 7

    async def discover(self) -> list[DeviceSpec]:
        """Find disks, including disks behind RAID controllers."""
        if self.smartctl_version is None:
            await self.check_smartctl()
        args = ["--scan-open"]
        if self.supports_json:
            args.append("--json=c")
        result = await self._smartctl(args)
        specs = parse_scan(result.stdout)
        if specs:
            return specs

        _LOGGER.debug("smartctl --scan-open found nothing, falling back to lsblk")
        result = await self._shell(
            "lsblk -d -J -o NAME,TYPE 2>/dev/null || lsblk -d -n -o NAME,TYPE"
        )
        return parse_lsblk(result.stdout)

    async def get_disk(self, spec: DeviceSpec, *, skip_standby: bool = True) -> Disk:
        """Read SMART data from one disk.

        With ``skip_standby`` a sleeping disk is not woken up; the result then
        has ``standby`` set and carries no SMART values.
        """
        if self.smartctl_version is None:
            await self.check_smartctl()
        args = ["-a"]
        if self.supports_json:
            args.insert(0, "--json=c")
        if skip_standby:
            args += ["-n", "standby"]
        result = await self._smartctl([*args, *spec.args()])
        disk = parse_smartctl(spec, result.stdout, result.exit_status)
        if disk.error and "permission denied" in disk.error.lower():
            disk.error += (
                "; run smartctl as root, enable sudo, or give the user access "
                "to the disk devices"
            )
        return disk

    async def get_disks(
        self,
        specs: Sequence[DeviceSpec] | None = None,
        *,
        skip_standby: bool = True,
    ) -> list[Disk]:
        """Read SMART data from the given disks, or from all discovered disks."""
        if specs is None:
            specs = await self.discover()
        disks = await asyncio.gather(
            *(self.get_disk(spec, skip_standby=skip_standby) for spec in specs)
        )
        return deduplicate(disks)

    async def start_self_test(
        self, spec: DeviceSpec, test_type: SelfTestType = SelfTestType.SHORT
    ) -> str:
        """Start a self-test; smartctl returns as soon as the disk accepted it."""
        result = await self._smartctl(["-t", test_type.value, *spec.args()])
        if result.exit_status & (EXIT_COMMAND_LINE | EXIT_DEVICE_OPEN):
            raise SmartctlCommandError(
                f"Could not start {test_type} self-test on {spec.key}: "
                f"{(result.stdout or result.stderr).strip()[-500:]}"
            )
        return result.stdout

    async def abort_self_test(self, spec: DeviceSpec) -> None:
        """Abort a running self-test."""
        result = await self._smartctl(["-X", *spec.args()])
        if result.exit_status & (EXIT_COMMAND_LINE | EXIT_DEVICE_OPEN):
            raise SmartctlCommandError(
                f"Could not abort self-test on {spec.key}: "
                f"{(result.stdout or result.stderr).strip()[-500:]}"
            )


def _text(value: str | bytes | None) -> str:
    if value is None:
        return ""
    if isinstance(value, bytes):
        return value.decode("utf-8", errors="replace")
    return value
