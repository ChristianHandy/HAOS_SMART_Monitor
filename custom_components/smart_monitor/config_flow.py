"""Config flow for SMART Disk Monitor."""

from collections.abc import Mapping
from typing import Any, override

from aiosmartctl import (
    DeviceSpec,
    HostInfo,
    SmartctlAuthenticationError,
    SmartctlConnectionError,
    SmartctlError,
    SmartctlHostKeyError,
    SmartctlNotFoundError,
    SmartctlPermissionError,
    fetch_host_key,
    host_key_fingerprint,
    validate_private_key,
)
import probatio

from homeassistant.config_entries import (
    ConfigFlow,
    ConfigFlowResult,
    OptionsFlowWithReload,
)
from homeassistant.const import (
    CONF_DEVICES,
    CONF_HOST,
    CONF_PASSWORD,
    CONF_PORT,
    CONF_USERNAME,
)
from homeassistant.core import callback
from homeassistant.helpers.selector import (
    BooleanSelector,
    NumberSelector,
    NumberSelectorConfig,
    NumberSelectorMode,
    TextSelector,
    TextSelectorConfig,
    TextSelectorType,
)

from . import create_client
from .const import (
    CONF_HOST_KEY,
    CONF_PRIVATE_KEY,
    CONF_SKIP_STANDBY,
    CONF_USE_SUDO,
    DEFAULT_PORT,
    DEFAULT_SKIP_STANDBY,
    DOMAIN,
    LOGGER,
)
from .coordinator import SmartMonitorConfigEntry

_PASSWORD = TextSelector(TextSelectorConfig(type=TextSelectorType.PASSWORD))
_PRIVATE_KEY = TextSelector(TextSelectorConfig(multiline=True))
_PORT = NumberSelector(
    NumberSelectorConfig(min=1, max=65535, step=1, mode=NumberSelectorMode.BOX)
)

USER_SCHEMA = probatio.Schema(
    {
        probatio.Required(CONF_HOST): TextSelector(),
        probatio.Required(CONF_PORT, default=DEFAULT_PORT): _PORT,
        probatio.Required(CONF_USERNAME, default="root"): TextSelector(),
        probatio.Optional(CONF_PASSWORD): _PASSWORD,
        probatio.Optional(CONF_PRIVATE_KEY): _PRIVATE_KEY,
        probatio.Required(CONF_USE_SUDO, default=False): BooleanSelector(),
    }
)
CREDENTIALS_SCHEMA = probatio.Schema(
    {
        probatio.Optional(CONF_PASSWORD): _PASSWORD,
        probatio.Optional(CONF_PRIVATE_KEY): _PRIVATE_KEY,
    }
)
RECONFIGURE_SCHEMA = probatio.Schema(
    {
        probatio.Required(CONF_HOST): TextSelector(),
        probatio.Required(CONF_PORT): _PORT,
        probatio.Required(CONF_USERNAME): TextSelector(),
        probatio.Required(CONF_USE_SUDO): BooleanSelector(),
    }
)
OPTIONS_SCHEMA = probatio.Schema(
    {
        probatio.Required(CONF_SKIP_STANDBY): BooleanSelector(),
        probatio.Optional(CONF_DEVICES): TextSelector(
            TextSelectorConfig(multiline=True)
        ),
    }
)


def _normalize(user_input: dict[str, Any]) -> dict[str, Any]:
    """Drop empty secrets and make the port an integer."""
    data = {key: value for key, value in user_input.items() if value != ""}
    if CONF_PORT in data:
        data[CONF_PORT] = int(data[CONF_PORT])
    if CONF_PRIVATE_KEY in data:
        data[CONF_PRIVATE_KEY] = data[CONF_PRIVATE_KEY].strip() + "\n"
    return data


def _validate_credentials(data: Mapping[str, Any]) -> str | None:
    """Return an error key when the credentials cannot work."""
    if not data.get(CONF_PASSWORD) and not data.get(CONF_PRIVATE_KEY):
        return "missing_credentials"
    if private_key := data.get(CONF_PRIVATE_KEY):
        try:
            validate_private_key(private_key)
        except ValueError:
            return "invalid_private_key"
    return None


async def _async_validate(data: Mapping[str, Any]) -> HostInfo:
    """Log in with a pinned host key and make sure smartctl runs."""
    async with create_client(data).session() as session:
        return await session.get_host_info()


def _error_key(err: SmartctlError) -> str:
    if isinstance(err, SmartctlHostKeyError):
        return "host_key_changed"
    if isinstance(err, SmartctlAuthenticationError):
        return "invalid_auth"
    if isinstance(err, SmartctlNotFoundError):
        return "smartctl_not_found"
    if isinstance(err, SmartctlPermissionError):
        return "sudo_failed"
    if isinstance(err, SmartctlConnectionError):
        return "cannot_connect"
    return "unknown"


class SmartMonitorOptionsFlow(OptionsFlowWithReload):
    """Options for SMART Disk Monitor."""

    async def async_step_init(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Manage the options."""
        errors: dict[str, str] = {}
        if user_input is not None:
            devices = [
                line.strip()
                for line in user_input.get(CONF_DEVICES, "").splitlines()
                if line.strip()
            ]
            try:
                for device in devices:
                    DeviceSpec.parse(device)
            except ValueError:
                errors[CONF_DEVICES] = "invalid_device"
            else:
                return self.async_create_entry(
                    data={
                        CONF_SKIP_STANDBY: user_input[CONF_SKIP_STANDBY],
                        CONF_DEVICES: devices,
                    }
                )

        options = self.config_entry.options
        suggested = user_input or {
            CONF_SKIP_STANDBY: options.get(CONF_SKIP_STANDBY, DEFAULT_SKIP_STANDBY),
            CONF_DEVICES: "\n".join(options.get(CONF_DEVICES, [])),
        }
        return self.async_show_form(
            step_id="init",
            data_schema=self.add_suggested_values_to_schema(OPTIONS_SCHEMA, suggested),
            errors=errors,
        )


class SmartMonitorConfigFlow(ConfigFlow, domain=DOMAIN):
    """Handle a config flow for SMART Disk Monitor."""

    VERSION = 1

    def __init__(self) -> None:
        """Initialize the flow."""
        self._data: dict[str, Any] = {}

    @staticmethod
    @callback
    @override
    def async_get_options_flow(
        config_entry: SmartMonitorConfigEntry,
    ) -> SmartMonitorOptionsFlow:
        """Return the options flow."""
        return SmartMonitorOptionsFlow()

    async def _async_fetch_host_key(self, data: Mapping[str, Any]) -> str | None:
        """Fetch the host key and remember it, or return None when unreachable."""
        try:
            host_key = await fetch_host_key(data[CONF_HOST], data[CONF_PORT])
        except SmartctlConnectionError as err:
            LOGGER.debug("Cannot fetch host key: %s", err)
            return None
        self._data[CONF_HOST_KEY] = host_key
        return host_key

    @override
    async def async_step_user(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Ask for the host and credentials."""
        errors: dict[str, str] = {}
        if user_input is not None:
            data = _normalize(user_input)
            if error := _validate_credentials(data):
                errors["base"] = error
            else:
                self._data = data
                if await self._async_fetch_host_key(data) is None:
                    errors["base"] = "cannot_connect"
                else:
                    return await self.async_step_confirm_host_key()

        return self.async_show_form(
            step_id="user",
            data_schema=self.add_suggested_values_to_schema(
                USER_SCHEMA, user_input or {}
            ),
            errors=errors,
        )

    async def async_step_confirm_host_key(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Let the user check the host key before any credentials are sent."""
        host_key = self._data[CONF_HOST_KEY]
        fingerprint = host_key_fingerprint(host_key)
        if user_input is None:
            return self.async_show_form(
                step_id="confirm_host_key",
                description_placeholders={
                    "host": self._data[CONF_HOST],
                    "fingerprint": fingerprint,
                },
            )

        await self.async_set_unique_id(fingerprint)
        self._abort_if_unique_id_configured()
        try:
            host_info = await _async_validate(self._data)
        except SmartctlError as err:
            LOGGER.debug("Validation failed: %s", err)
            error = _error_key(err)
        except Exception:  # noqa: BLE001
            LOGGER.exception("Unexpected error")
            error = "unknown"
        else:
            return self.async_create_entry(
                title=host_info.hostname or self._data[CONF_HOST], data=self._data
            )

        return self.async_show_form(
            step_id="user",
            data_schema=self.add_suggested_values_to_schema(
                USER_SCHEMA,
                {
                    key: value
                    for key, value in self._data.items()
                    if key not in (CONF_PASSWORD, CONF_PRIVATE_KEY, CONF_HOST_KEY)
                },
            ),
            errors={"base": error},
        )

    async def async_step_reauth(
        self, entry_data: Mapping[str, Any]
    ) -> ConfigFlowResult:
        """Handle rejected credentials or a changed host key."""
        return await self.async_step_reauth_confirm()

    async def async_step_reauth_confirm(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Ask for new credentials and confirm the current host key."""
        entry = self._get_reauth_entry()
        errors: dict[str, str] = {}

        # Pin the key the user is shown, not one fetched again on submit.
        host_key = self._data.get(CONF_HOST_KEY) or await self._async_fetch_host_key(
            entry.data
        )
        if host_key is None:
            return self.async_abort(reason="cannot_connect")
        fingerprint = host_key_fingerprint(host_key)

        if user_input is not None:
            data = {
                CONF_HOST: entry.data[CONF_HOST],
                CONF_PORT: entry.data[CONF_PORT],
                CONF_USERNAME: entry.data[CONF_USERNAME],
                CONF_USE_SUDO: entry.data.get(CONF_USE_SUDO, False),
                **_normalize(user_input),
                CONF_HOST_KEY: host_key,
            }
            if error := _validate_credentials(data):
                errors["base"] = error
            else:
                try:
                    await _async_validate(data)
                except SmartctlError as err:
                    errors["base"] = _error_key(err)
                except Exception:  # noqa: BLE001
                    LOGGER.exception("Unexpected error")
                    errors["base"] = "unknown"
                else:
                    return self.async_update_reload_and_abort(
                        entry, unique_id=fingerprint, data=data
                    )

        changed = entry.data.get(CONF_HOST_KEY) not in (None, host_key)
        return self.async_show_form(
            step_id="reauth_host_key_changed" if changed else "reauth_confirm",
            data_schema=CREDENTIALS_SCHEMA,
            errors=errors,
            description_placeholders={
                "host": entry.data[CONF_HOST],
                "fingerprint": fingerprint,
            },
        )

    async def async_step_reauth_host_key_changed(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Handle the reauth form shown after the host key changed."""
        return await self.async_step_reauth_confirm(user_input)

    async def async_step_reconfigure(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Change the address or user of a host."""
        entry = self._get_reconfigure_entry()
        errors: dict[str, str] = {}

        if user_input is not None:
            data = {**entry.data, **_normalize(user_input)}
            host_key = await self._async_fetch_host_key(data)
            if host_key is None:
                errors["base"] = "cannot_connect"
            else:
                await self.async_set_unique_id(host_key_fingerprint(host_key))
                self._abort_if_unique_id_mismatch(reason="different_host")
                data[CONF_HOST_KEY] = host_key
                try:
                    await _async_validate(data)
                except SmartctlError as err:
                    errors["base"] = _error_key(err)
                except Exception:  # noqa: BLE001
                    LOGGER.exception("Unexpected error")
                    errors["base"] = "unknown"
                else:
                    return self.async_update_reload_and_abort(entry, data=data)

        return self.async_show_form(
            step_id="reconfigure",
            data_schema=self.add_suggested_values_to_schema(
                RECONFIGURE_SCHEMA,
                user_input
                or {
                    CONF_HOST: entry.data[CONF_HOST],
                    CONF_PORT: entry.data[CONF_PORT],
                    CONF_USERNAME: entry.data[CONF_USERNAME],
                    CONF_USE_SUDO: entry.data.get(CONF_USE_SUDO, False),
                },
            ),
            errors=errors,
        )
