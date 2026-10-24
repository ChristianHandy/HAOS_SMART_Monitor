"""Exceptions for aiosmartctl."""


class SmartctlError(Exception):
    """Base exception for aiosmartctl."""


class SmartctlConnectionError(SmartctlError):
    """The host could not be reached or the connection dropped."""


class SmartctlAuthenticationError(SmartctlError):
    """The host rejected the credentials."""


class SmartctlHostKeyError(SmartctlError):
    """The host presented a different SSH host key than the trusted one."""


class SmartctlNotFoundError(SmartctlError):
    """smartctl is not installed on the host."""


class SmartctlPermissionError(SmartctlError):
    """smartctl, or sudo for it, is not allowed for this user."""


class SmartctlCommandError(SmartctlError):
    """A smartctl command failed."""
