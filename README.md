# SMART Disk Monitor – Home Assistant Integration

Monitor SMART health data from all disks on remote servers (**Unraid**, **Proxmox**, **generic Linux**, **desktop Ubuntu**) directly in Home Assistant via SSH.

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
  - Last self-test result and date
- 🔘 Buttons per disk:
  - **Run Short Self-Test** (~2 min)
  - **Run Long Self-Test** (thorough, hours)
  - **Run Conveyance Self-Test** (~5 min)
  - **Download SMART Report** (saves full report to `/config/smart_reports/`)
- 🔔 Binary sensors for instant alerts:
  - **Health Problem** – fires when `smartctl` reports FAILED
  - **Sector Problem** – fires when bad/pending/uncorrectable sectors > 0
- Supports **HDD**, **SSD**, and **NVMe** drives
- Configurable poll interval (default: 5 minutes)
- Multiple servers supported (add one entry per server)

---

## Requirements

### Home Assistant side
- Home Assistant **2023.6+**
- Python package `paramiko` (installed automatically via `requirements`)

### Remote server side
- SSH access enabled
- `smartmontools` installed (see per-OS instructions below)

---

## Server Setup by OS

> ⚠️ **This is the most important section.** Skipping these steps is the most common reason sensors show "Unknown".

### Unraid

smartmontools is pre-installed and SSH runs as `root` — no extra setup needed.

```
Username: root
Password: your Unraid root password
```

### Proxmox

smartmontools is pre-installed and SSH runs as `root` — no extra setup needed.

```
Username: root
Password: your Proxmox root password
```

### Debian / Ubuntu Server (headless)

```bash
# Install smartmontools
apt install smartmontools

# Option A — connect as root (simplest)
# Make sure PermitRootLogin is enabled in /etc/ssh/sshd_config

# Option B — connect as a regular user, grant sudo access to smartctl
echo 'YOUR_USER ALL=(ALL) NOPASSWD: /usr/sbin/smartctl' > /etc/sudoers.d/smart-monitor
chmod 440 /etc/sudoers.d/smart-monitor
```

### Ubuntu Desktop (most involved — read carefully)

Ubuntu Desktop has **AppArmor** enabled and regular users are not in the `disk` group by default. Both issues must be fixed for smartctl to access disk devices over SSH.

**Step 1 — Install smartmontools**
```bash
sudo apt install smartmontools
```

**Step 2 — Add your SSH user to the `disk` group**
```bash
sudo usermod -aG disk YOUR_USERNAME
```

**Step 3 — Fix AppArmor** so smartctl can open block devices in SSH sessions
```bash
sudo aa-complain /usr/sbin/smartctl
```

Or create a local override (more precise than complain mode):
```bash
sudo mkdir -p /etc/apparmor.d/local
cat << 'AAEOF' | sudo tee /etc/apparmor.d/local/usr.sbin.smartctl
/dev/sd* rw,
/dev/nvme* rw,
/dev/hd* rw,
AAEOF
sudo apparmor_parser -r /etc/apparmor.d/usr.sbin.smartctl 2>/dev/null || true
```

**Step 4 — Reboot**

> ⚠️ Group membership changes **require a full reboot** to take effect for SSH sessions. A logout/login is not enough.

```bash
sudo reboot
```

**Step 5 — Verify it works**
```bash
ssh YOUR_USERNAME@localhost "groups | grep disk && smartctl -a /dev/sda 2>&1 | head -5"
```

You should see `disk` in the groups line and smartctl showing disk info — not "Permission denied".

**Why is this needed?**

When you run `smartctl` interactively in a terminal it works because your desktop session already has the `disk` group active. SSH sessions start fresh and only get the groups that were active at last login — which is why a reboot (not just logout) is required after `usermod -aG disk`.

AppArmor additionally restricts smartctl from opening raw block devices in non-interactive sessions. `aa-complain` switches it from blocking to logging-only.

---

## Installation

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
        ├── button.py
        ├── strings.json
        └── translations/
            └── en.json
```

Restart Home Assistant after copying.

---

## Configuration

1. **Settings → Devices & Services → Add Integration** → search *SMART Disk Monitor*
2. Fill in:

| Field | Example | Notes |
|---|---|---|
| Hostname / IP | `192.168.1.10` | IP or hostname of the remote machine |
| SSH Port | `22` | Default for all OS types |
| Username | `christian` | The SSH user you set up above |
| Password | `••••` | Or leave blank if using a key |
| SSH Key Path | `/config/ssh/id_ed25519` | Path *inside the HA container* |
| Server Type | `generic_linux` | Label only, used for display |
| Scan Interval | `300` | Seconds; 300 = 5 minutes |

3. Click **Submit** — HA will test the SSH connection.
4. Repeat for each server.

---

## Entities Created

For a server `192.168.1.10` with disk `/dev/sda`:

| Entity | Type | Description |
|---|---|---|
| `sensor.…_health` | sensor | PASSED / FAILED / UNKNOWN |
| `sensor.…_temperature` | sensor | °C |
| `sensor.…_power_on_hours` | sensor | Hours |
| `sensor.…_power_cycles` | sensor | Count |
| `sensor.…_reallocated_sectors` | sensor | Count (HDD/SSD) |
| `sensor.…_pending_sectors` | sensor | Count (HDD/SSD) |
| `sensor.…_uncorrectable_sectors` | sensor | Count (HDD/SSD) |
| `sensor.…_last_self_test` | sensor | Last test result + date |
| `binary_sensor.…_health_problem` | binary | On = FAILED |
| `binary_sensor.…_sector_problem` | binary | On = any bad sectors |
| `button.…_run_short_self_test` | button | Starts short test |
| `button.…_run_long_self_test` | button | Starts long test |
| `button.…_run_conveyance_self_test` | button | Starts conveyance test |
| `button.…_download_smart_report` | button | Saves full report to `/config/smart_reports/` |

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
        message: "Disk /dev/sda is {{ states('sensor.nas_dev_sda_temperature') }}°C!"
```

---

## Troubleshooting

### Sensors all show "Unknown" / "Unbekannt"

This means the SSH connection works but `smartctl` cannot open the disk device. Check the HA logs (*Settings → System → Logs*, filter `smart_monitor`) for the exact error.

**"Permission denied" on the device**

Follow the full [Ubuntu Desktop setup](#ubuntu-desktop-most-involved--read-carefully) section above. The two most common causes are:
- User not in the `disk` group → `sudo usermod -aG disk YOUR_USER` + reboot
- AppArmor blocking SSH sessions → `sudo aa-complain /usr/sbin/smartctl`

**smartctl not found**

```bash
which smartctl || apt install smartmontools
```

### Cannot connect at all

```bash
# Test SSH manually from another machine
ssh YOUR_USER@192.168.1.x

# Check SSH is running
systemctl status ssh
```

### Buttons not appearing

Buttons appear under **"Steuerungen"** (Controls) on the device page, not under "Sensoren". If still missing, go to **Settings → Devices & Services → SMART Disk Monitor → ⋮ → Reload**.

### SSH key not found

The key path must be accessible from *within the Home Assistant container*. Store it under `/config/` and reference it as `/config/ssh/id_ed25519`.

---

## License

MIT – see `LICENSE`
