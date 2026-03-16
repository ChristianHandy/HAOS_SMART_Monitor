"""Constants for the SMART Disk Monitor integration."""

DOMAIN = "smart_monitor"
CONF_HOST = "host"
CONF_PORT = "port"
CONF_USERNAME = "username"
CONF_PASSWORD = "password"
CONF_SSH_KEY = "ssh_key"
CONF_SERVER_TYPE = "server_type"
CONF_SCAN_INTERVAL = "scan_interval"

SERVER_TYPE_UNRAID = "unraid"
SERVER_TYPE_PROXMOX = "proxmox"
SERVER_TYPE_GENERIC_LINUX = "generic_linux"

SERVER_TYPES = [SERVER_TYPE_UNRAID, SERVER_TYPE_PROXMOX, SERVER_TYPE_GENERIC_LINUX]

DEFAULT_PORT = 22
DEFAULT_SCAN_INTERVAL = 300  # seconds (5 minutes)

# SMART attribute IDs we care about
SMART_ATTRS = {
    1:   {"name": "Raw Read Error Rate",       "icon": "mdi:alert-circle"},
    3:   {"name": "Spin Up Time",               "icon": "mdi:timer"},
    4:   {"name": "Start/Stop Count",           "icon": "mdi:counter"},
    5:   {"name": "Reallocated Sectors Count",  "icon": "mdi:alert"},
    7:   {"name": "Seek Error Rate",            "icon": "mdi:alert-circle-outline"},
    9:   {"name": "Power On Hours",             "icon": "mdi:clock-outline"},
    10:  {"name": "Spin Retry Count",           "icon": "mdi:rotate-right"},
    12:  {"name": "Power Cycle Count",          "icon": "mdi:power"},
    177: {"name": "Wear Leveling Count",        "icon": "mdi:chart-line"},
    187: {"name": "Reported Uncorrectable",     "icon": "mdi:close-circle"},
    188: {"name": "Command Timeout",            "icon": "mdi:timer-off"},
    190: {"name": "Airflow Temperature",        "icon": "mdi:thermometer"},
    194: {"name": "Temperature",                "icon": "mdi:thermometer"},
    196: {"name": "Reallocation Event Count",   "icon": "mdi:alert"},
    197: {"name": "Current Pending Sector",     "icon": "mdi:alert-outline"},
    198: {"name": "Offline Uncorrectable",      "icon": "mdi:close-circle-outline"},
    199: {"name": "UDMA CRC Error Count",       "icon": "mdi:lan-disconnect"},
    231: {"name": "SSD Life Left",              "icon": "mdi:battery"},
    233: {"name": "Media Wearout Indicator",    "icon": "mdi:harddisk"},
}

# NVMe specific attributes
NVME_ATTRS = {
    "temperature":                    {"name": "Temperature",              "icon": "mdi:thermometer",     "unit": "°C"},
    "available_spare":                {"name": "Available Spare",          "icon": "mdi:battery",         "unit": "%"},
    "available_spare_threshold":      {"name": "Available Spare Threshold","icon": "mdi:battery-alert",   "unit": "%"},
    "percentage_used":                {"name": "Percentage Used",          "icon": "mdi:chart-pie",       "unit": "%"},
    "data_units_read":                {"name": "Data Units Read",          "icon": "mdi:download",        "unit": ""},
    "data_units_written":             {"name": "Data Units Written",       "icon": "mdi:upload",          "unit": ""},
    "power_on_hours":                 {"name": "Power On Hours",           "icon": "mdi:clock-outline",   "unit": "h"},
    "power_cycles":                   {"name": "Power Cycles",             "icon": "mdi:power",           "unit": ""},
    "unsafe_shutdowns":               {"name": "Unsafe Shutdowns",         "icon": "mdi:power-off",       "unit": ""},
    "media_errors":                   {"name": "Media Errors",             "icon": "mdi:alert",           "unit": ""},
    "num_err_log_entries":            {"name": "Error Log Entries",        "icon": "mdi:format-list-text","unit": ""},
}

# Health status levels
HEALTH_PASSED = "PASSED"
HEALTH_FAILED = "FAILED"
HEALTH_UNKNOWN = "UNKNOWN"
