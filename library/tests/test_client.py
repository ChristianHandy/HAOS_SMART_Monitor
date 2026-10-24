"""Tests for the SSH client against an in-process SSH server."""

from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator
from dataclasses import dataclass

import asyncssh
import pytest

from aiosmartctl import (
    SmartctlAuthenticationError,
    SmartctlClient,
    SmartctlConnectionError,
    SmartctlHostKeyError,
    fetch_host_key,
    host_key_fingerprint,
    validate_private_key,
)

from .conftest import FakeHost, load_fixture, smartctl

USERNAME = "monitor"
PASSWORD = "correct horse"


@dataclass
class Server:
    """A running test SSH server."""

    port: int
    host_key: str
    client_key: str
    fake: FakeHost


class _Auth(asyncssh.SSHServer):
    def __init__(self, client_key: asyncssh.SSHKey) -> None:
        self._client_key = client_key

    def begin_auth(self, username: str) -> bool:
        return True

    def password_auth_supported(self) -> bool:
        return True

    def validate_password(self, username: str, password: str) -> bool:
        return username == USERNAME and password == PASSWORD

    def public_key_auth_supported(self) -> bool:
        return True

    def validate_public_key(self, username: str, key: asyncssh.SSHKey) -> bool:
        return username == USERNAME and (
            key.export_public_key() == self._client_key.export_public_key()
        )


@pytest.fixture
async def server(host: FakeHost) -> AsyncIterator[Server]:
    """Run an SSH server that answers like a host with smartctl."""
    host_key = asyncssh.generate_private_key("ssh-ed25519")
    client_key = asyncssh.generate_private_key("ssh-ed25519")

    async def handle(process: asyncssh.SSHServerProcess) -> None:
        if "sleep" in (process.command or ""):
            await asyncio.sleep(5)
        result = await host(process.command or "")
        process.stdout.write(result.stdout)
        process.stderr.write(result.stderr)
        process.exit(result.exit_status)

    listener = await asyncssh.listen(
        "127.0.0.1",
        0,
        server_host_keys=[host_key],
        server_factory=lambda: _Auth(client_key),
        process_factory=handle,
    )
    try:
        yield Server(
            port=listener.get_port(),
            host_key=host_key.export_public_key().decode().strip(),
            client_key=client_key.export_private_key().decode(),
            fake=host,
        )
    finally:
        listener.close()
        await listener.wait_closed()


def _client(server: Server, **kwargs: object) -> SmartctlClient:
    options: dict[str, object] = {
        "port": server.port,
        "username": USERNAME,
        "password": PASSWORD,
        "known_host_key": server.host_key,
    }
    options.update(kwargs)
    return SmartctlClient("127.0.0.1", **options)  # type: ignore[arg-type]


async def test_password_login(server: Server) -> None:
    """Test reading disks after logging in with a password."""
    server.fake.respond(
        smartctl("--scan-open"), '{"devices": [{"name": "/dev/sda", "type": "sat"}]}'
    )
    server.fake.respond(smartctl("/dev/sda"), load_fixture("ata_hdd.json"))

    async with _client(server).session() as session:
        disks = await session.get_disks()

    assert session.host_key == server.host_key
    assert disks[0].serial == "WD-WCC7K1234567"


async def test_private_key_login(server: Server) -> None:
    """Test logging in with a private key."""
    client = _client(server, password=None, private_key=server.client_key)

    async with client.session() as session:
        assert await session.check_smartctl() == "7.4"


async def test_wrong_password(server: Server) -> None:
    """Test that rejected credentials raise an authentication error."""
    with pytest.raises(SmartctlAuthenticationError):
        async with _client(server, password="wrong").session():
            pass


async def test_invalid_private_key(server: Server) -> None:
    """Test that an unreadable private key raises an authentication error."""
    with pytest.raises(SmartctlAuthenticationError, match="Invalid private key"):
        async with _client(server, private_key="not a key").session():
            pass


async def test_unexpected_host_key(server: Server) -> None:
    """Test that a changed host key is refused."""
    other = asyncssh.generate_private_key("ssh-ed25519").export_public_key().decode()

    with pytest.raises(SmartctlHostKeyError):
        async with _client(server, known_host_key=other).session():
            pass


async def test_no_host_key_verification(server: Server) -> None:
    """Test that verification can be skipped to learn the host key."""
    async with _client(server, known_host_key=None).session() as session:
        assert session.host_key == server.host_key


async def test_command_timeout(server: Server) -> None:
    """Test that a hanging command raises a connection error."""
    async with _client(server, command_timeout=0.2).session() as session:
        with pytest.raises(SmartctlConnectionError, match="timed out"):
            await session._runner("sleep 10")


async def test_connection_refused(server: Server) -> None:
    """Test that an unreachable host raises a connection error."""
    listener = await asyncio.start_server(lambda r, w: w.close(), "127.0.0.1", 0)
    port = listener.sockets[0].getsockname()[1]
    listener.close()
    await listener.wait_closed()

    with pytest.raises(SmartctlConnectionError):
        async with _client(server, port=port).session():
            pass
    with pytest.raises(SmartctlConnectionError):
        await fetch_host_key("127.0.0.1", port)


async def test_lost_connection(server: Server) -> None:
    """Test that a dropped connection raises a connection error."""
    async with _client(server).session() as session:
        pass

    with pytest.raises(SmartctlConnectionError, match="Lost connection"):
        await session.check_smartctl()


async def test_fetch_host_key(server: Server) -> None:
    """Test fetching and fingerprinting the host key."""
    key = await fetch_host_key("127.0.0.1", server.port)

    assert key == server.host_key
    assert host_key_fingerprint(key).startswith("SHA256:")


def test_key_validation(server: Server) -> None:
    """Test validating user supplied keys."""
    validate_private_key(server.client_key)
    with pytest.raises(ValueError):
        validate_private_key("-----BEGIN OPENSSH PRIVATE KEY-----\nbroken\n")
    with pytest.raises(ValueError):
        host_key_fingerprint("ssh-ed25519 broken")
