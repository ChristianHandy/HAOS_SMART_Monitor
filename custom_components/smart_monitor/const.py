"""Constants for the SMART Disk Monitor integration."""

from datetime import timedelta
import logging

DOMAIN = "smart_monitor"
LOGGER = logging.getLogger(__package__)

SCAN_INTERVAL = timedelta(minutes=5)

CONF_HOST_KEY = "host_key"
CONF_PRIVATE_KEY = "private_key"
CONF_USE_SUDO = "use_sudo"
CONF_SKIP_STANDBY = "skip_standby"

DEFAULT_PORT = 22
DEFAULT_SKIP_STANDBY = True
