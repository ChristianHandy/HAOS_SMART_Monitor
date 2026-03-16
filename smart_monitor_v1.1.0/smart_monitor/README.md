# SMART Disk Monitor – Home Assistant Integration

Monitor SMART health data from all disks on remote servers (**Unraid**, **Proxmox**, generic Linux) directly in Home Assistant via SSH.

---

## Features

- ✅ Connects to remote servers via **SSH** (password or key-based auth)
- 🖴 Auto-discovers all block devices (`/dev/sda`, `/dev/nvme0n1`, …)
- 📊 Creates sensors for every disk:
  - Health status (PASSED / FAILED / UNKNOWN)
  - Temperature (°C)
  - Power-on hours
  - Power cycles
  - Reallocated sectors *(HDD/SSD)*
  - Pending sectors *(HDD/SSD)*
  - Uncorrectable sectors *(HDD/SSD)*
  - Available spare, % used, media errors *(NVMe)*
- 🔔 Binary sensors for instant alerts:
  - **Health Problem** – fires when `smartctl` reports FAILED
  - **Sector Problem** – fires when bad/pending/uncorrectable sectors > 0
- Supports **HDD**, **SSD**, and **NVMe** drives
- JSON output path used when `smartctl ≥ 7.0` is available; falls back to text parsing
- Configurable poll interval (default: 5 minutes)
- Multiple servers supported (add one entry per server)

---

## Requirements

### Home Assistant side
- Home Assistant **2023.6+**
- Python package `paramiko` (installed automatically via `requirements`)

### Remote server side
- SSH access enabled
- `smartmontools` installed:
  ```bash
  # Debian/Ubuntu
  apt install smartmontools

  # Unraid: already included
  # Proxmox: apt install smartmontools
  ```
- The SSH user needs `sudo` access to run `smartctl` **without a password**:
  ```
  # /etc/sudoers.d/ha-smart
  ha_user ALL=(ALL) NOPASSWD: /usr/sbin/smartctl
  ```

---

## Installation

### HACS (recommended)

1. Open HACS → **Integrations** → ⋮ → *Custom repositories*
2. Add `https://github.com/your-repo/ha-smart-monitor` as an **Integration**
3. Install **SMART Disk Monitor**
4. Restart Home Assistant

### Manual

```
config/
└── custom_components/
    └── smart_monitor/          ← copy this folder
        ├── __init__.py
        ├── manifest.json
        ├── config_flow.py
        ├── coordinator.py
        ├── const.py
        ├── smart_fetcher.py
        ├── sensor.py
        ├── binary_sensor.py
        ├── strings.json
        └── translations/
            └── en.json
```

Restart Home Assistant.

---

## Configuration

1. **Settings → Devices & Services → Add Integration** → search *SMART Disk Monitor*
2. Fill in:

| Field | Example | Notes |
|---|---|---|
| Hostname / IP | `192.168.1.10` | |
| SSH Port | `22` | Unraid/Proxmox default |
| Username | `root` | Proxmox default; Unraid uses `root` |
| Password | `••••` | Or leave blank if using a key |
| SSH Key Path | `/config/ssh/id_ed25519` | Path *inside the HA container* |
| Server Type | `unraid` | Label only, doesn't change logic |
| Scan Interval | `300` | Seconds; 300 = 5 minutes |

3. Click **Submit** – HA will test the SSH connection.
4. Repeat for each server.

---

## Entities Created

For a server `192.168.1.10` with disks `/dev/sda` and `/dev/nvme0n1`:

| Entity ID | Type | Description |
|---|---|---|
| `sensor.192_168_1_10_dev_sda_health` | sensor | PASSED / FAILED / UNKNOWN |
| `sensor.192_168_1_10_dev_sda_temperature` | sensor | °C |
| `sensor.192_168_1_10_dev_sda_power_on_hours` | sensor | Hours |
| `sensor.192_168_1_10_dev_sda_power_cycles` | sensor | Count |
| `sensor.192_168_1_10_dev_sda_reallocated_sectors` | sensor | Count |
| `sensor.192_168_1_10_dev_sda_pending_sectors` | sensor | Count |
| `sensor.192_168_1_10_dev_sda_uncorrectable_sectors` | sensor | Count |
| `binary_sensor.192_168_1_10_dev_sda_health_problem` | binary | On = FAILED |
| `binary_sensor.192_168_1_10_dev_sda_sector_problem` | binary | On = any bad sectors |
| `sensor.192_168_1_10_dev_nvme0n1_temperature` | sensor | °C |
| `sensor.192_168_1_10_dev_nvme0n1_available_spare` | sensor | % |
| `sensor.192_168_1_10_dev_nvme0n1_percentage_used` | sensor | % |
| `sensor.192_168_1_10_dev_nvme0n1_media_errors` | sensor | Count |

---

## Automation Examples

### Alert when any disk fails health check

```yaml
automation:
  alias: "Disk SMART failure alert"
  trigger:
    - platform: state
      entity_id:
        - binary_sensor.nas_dev_sda_health_problem
        - binary_sensor.nas_dev_sdb_health_problem
      to: "on"
  action:
    - service: notify.mobile_app_my_phone
      data:
        title: "⚠️ Disk Health Alert"
        message: "{{ trigger.to_state.name }} is reporting a SMART failure!"
```

### Alert on high disk temperature

```yaml
automation:
  alias: "Disk overheating alert"
  trigger:
    - platform: numeric_state
      entity_id: sensor.nas_dev_sda_temperature
      above: 55
  action:
    - service: notify.notify
      data:
        message: "Disk /dev/sda temperature is {{ states('sensor.nas_dev_sda_temperature') }}°C!"
```

---

## Troubleshooting

**Cannot connect**
- Verify the SSH port and credentials manually: `ssh user@host`
- Ensure the HA container can reach the server (check firewall rules)

**No disks discovered**
- Confirm `lsblk` is installed on the server
- Check HA logs: *Settings → System → Logs* and filter for `smart_monitor`

**SMART data missing / all unknown**
- Confirm `smartctl` is installed: `which smartctl`
- Test manually: `sudo smartctl -a /dev/sda`
- Make sure `sudo` is passwordless for `smartctl`

**SSH key not found**
- The path must be accessible from *within the Home Assistant container*
- Store the key under `/config/` and reference it as `/config/ssh/id_ed25519`

---

## License

MIT – see `LICENSE`
