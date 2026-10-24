"""Fixtures for aiosmartctl tests."""

from __future__ import annotations

import json
import shlex
from collections.abc import Callable
from pathlib import Path
from typing import Any

import pytest

from aiosmartctl import CommandResult

FIXTURES = Path(__file__).parent / "fixtures"


def load_fixture(name: str) -> str:
    """Return the contents of a fixture file."""
    return (FIXTURES / name).read_text()


def load_json(name: str) -> dict[str, Any]:
    """Return a JSON fixture."""
    return json.loads(load_fixture(name))


class FakeHost:
    """Answers commands like a host with smartctl installed would."""

    def __init__(self) -> None:
        """Initialize the fake host."""
        self.commands: list[list[str]] = []
        self.responses: list[tuple[Callable[[list[str]], bool], CommandResult]] = []

    def respond(
        self,
        matcher: Callable[[list[str]], bool],
        stdout: str = "",
        *,
        exit_status: int = 0,
        stderr: str = "",
    ) -> None:
        """Answer commands that match with the given output."""
        self.responses.insert(
            0,
            (
                matcher,
                CommandResult(exit_status=exit_status, stdout=stdout, stderr=stderr),
            ),
        )

    async def __call__(self, command: str) -> CommandResult:
        """Run a command."""
        argv = _argv(command)
        self.commands.append(argv)
        for matcher, result in self.responses:
            if matcher(argv):
                return result
        return CommandResult(exit_status=127, stdout="", stderr="not found")


def _argv(command: str) -> list[str]:
    """Return the argv of the program a ``sh -c`` command execs."""
    outer = shlex.split(command)
    assert outer[:2] == ["sh", "-c"]
    script = outer[2]
    if "exec " in script:
        return shlex.split(script.split("exec ", 1)[1])
    return ["<script>", script]


def smartctl(*needles: str) -> Callable[[list[str]], bool]:
    """Match smartctl invocations that contain all needles."""

    def matcher(argv: list[str]) -> bool:
        if "smartctl" not in argv:
            return False
        return all(needle in argv for needle in needles)

    return matcher


@pytest.fixture
def host() -> FakeHost:
    """Return a fake host with smartctl 7.4."""
    fake = FakeHost()
    fake.respond(
        smartctl("--version"),
        "smartctl 7.4 2023-08-01 r5530 [x86_64-linux-6.8.12-4-pve] (local build)\n",
    )
    return fake
