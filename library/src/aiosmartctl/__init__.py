"""Asynchronous client for reading SMART data with smartctl over SSH."""

from .client import (
    CommandResult,
    CommandRunner,
    SmartctlClient,
    SmartctlSession,
    fetch_host_key,
    host_key_fingerprint,
    validate_private_key,
)
from .exceptions import (
    SmartctlAuthenticationError,
    SmartctlCommandError,
    SmartctlConnectionError,
    SmartctlError,
    SmartctlHostKeyError,
    SmartctlNotFoundError,
    SmartctlPermissionError,
)
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

__version__ = "0.1.0"

__all__ = [
    "AtaAttribute",
    "CommandResult",
    "CommandRunner",
    "DeviceSpec",
    "Disk",
    "DiskType",
    "HealthStatus",
    "HostInfo",
    "Interface",
    "SelfTestEntry",
    "SelfTestResult",
    "SelfTestType",
    "SmartctlAuthenticationError",
    "SmartctlClient",
    "SmartctlCommandError",
    "SmartctlConnectionError",
    "SmartctlError",
    "SmartctlHostKeyError",
    "SmartctlNotFoundError",
    "SmartctlPermissionError",
    "SmartctlSession",
    "fetch_host_key",
    "host_key_fingerprint",
    "validate_private_key",
]
