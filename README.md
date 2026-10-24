# SMART Disk Monitor for Home Assistant

Monitor the SMART health of the disks in your servers from Home Assistant.
The integration logs in over SSH, runs
[smartmontools](https://www.smartmontools.org/) `smartctl` and creates a
device with sensors for every disk: health, temperature, wear, error counters
and self-tests.

It works with Unraid, Proxmox VE, TrueNAS SCALE, Debian/Ubuntu and other
Linux or FreeBSD servers, including enterprise hardware: SAS disks, disks
behind MegaRAID/PERC and HP Smart Array controllers, and NVMe drives.

> [!IMPORTANT]
> Version 2.0 is a rewrite that prepares the integration for inclusion in
> Home Assistant core. See [Upgrading from 1.x](#upgrading-from-1x).

## Contents

- [Features](#features)
- [Supported hardware and test status](#supported-hardware-and-test-status)
- [Requirements](#requirements)
- [Installation](#installation)
- [Configuration](#configuration)
- [Entities](#entities)
- [Dashboard card](#dashboard-card)
- [Automation examples](#automation-examples)
- [Security](#security)
- [Troubleshooting](#troubleshooting)
- [Upgrading from 1.x](#upgrading-from-1x)
- [Development](#development)

## Features

- One device per host, with one device per disk underneath it
- Finds disks with `smartctl --scan-open`, including disks behind RAID
  controllers, and falls back to `lsblk`
- Disks smartctl cannot scan, such as disks behind an HP Smart Array, can be
  listed by hand (`/dev/sg0 cciss,0`)
- Does not wake up sleeping disks: their last values are kept and a
  **Standby** sensor shows they are asleep
- Start and abort short, long and conveyance self-tests
- Works with a non-root user through `sudo -n smartctl`
- Password or private key login; the SSH host key is confirmed when the host
  is added and checked on every connection
- Diagnostics download with serial numbers and credentials removed
- Reauthentication when the password or host key changes, and
  reconfiguration of the address, port, user and sudo setting

## Supported hardware and test status

> [!WARNING]
> **Not every connection type has been tested against real hardware.**
> Every disk type below is covered by automated tests that run the parsers on
> sample `smartctl` output and the SSH client against a simulated SSH server.
> That proves the code handles the documented output formats, not that every
> controller, firmware or operating system produces exactly that output.
> Version 2.0 has **not yet been run against real hardware** at all; the 1.x
> releases were used on Unraid, Proxmox VE and Ubuntu with SATA and NVMe
> disks.
>
> If you run it on hardware marked untested, please
> [open an issue](https://github.com/ChristianHandy/HAOS_SMART_Monitor/issues)
> with the result and, if something is wrong, the output of
> `smartctl --json -a <device>` (remove serial numbers if you like).

| Hardware or setup | How smartctl reaches it | Automated tests | Tested on real hardware |
|---|---|---|---|
| SATA hard disk | `-d sat` | ✅ | ⚠️ 1.x only |
| SATA SSD | `-d sat` | ✅ | ⚠️ 1.x only |
| NVMe SSD | `-d nvme` | ✅ | ⚠️ 1.x only |
| SAS hard disk or SSD | `-d scsi` | ✅ | ❌ Not yet |
| Disk behind LSI MegaRAID / Dell PERC | `-d megaraid,N` | ✅ | ❌ Not yet |
| Disk behind HP Smart Array (manual) | `-d cciss,N` | ✅ (parsing) | ❌ Not yet |
| Areca, 3ware, Adaptec (aacraid) | `-d areca,N`, `-d 3ware,N`, `-d aacraid,…` | ⚠️ Same code path, no sample output | ❌ Not yet |
| USB enclosure / bridge | `-d sat` and others | ✅ (no SMART reported) | ❌ Not yet |
| Multipath SAS (one disk, two paths) | — | ✅ (shown once) | ❌ Not yet |
| smartctl 6.x without JSON | text output | ✅ | ❌ Not yet |
| Unraid, Proxmox VE, Debian/Ubuntu host | SSH | ✅ (simulated) | ⚠️ 1.x only |
| TrueNAS SCALE, Synology DSM, FreeBSD / TrueNAS CORE | SSH | ✅ (simulated) | ❌ Not yet |
| Password, private key, sudo | SSH | ✅ (simulated SSH server) | ❌ Not yet |

Hardware RAID volumes themselves (for example `/dev/sda` on a PERC) are not
disks and report no SMART data; the physical disks behind the controller are
shown instead when the controller supports pass-through.

## Requirements

**Home Assistant** 2026.10 or newer.

**On every monitored host:**

- An SSH server you can log in to with a password or a private key
- smartmontools 7.0 or newer (6.x works with fewer details)
- Either the `root` user, or a user that may run smartctl with
  `sudo` without a password:

  ```bash
  sudo apt install smartmontools
  echo 'ha-smart ALL=(root) NOPASSWD: /usr/sbin/smartctl' | sudo tee /etc/sudoers.d/ha-smart
  sudo chmod 440 /etc/sudoers.d/ha-smart
  ```

  Then enable **Run smartctl with sudo** when you add the host.

Unraid and Proxmox VE ship smartmontools and log in as `root`, so they need
no preparation.

## Installation

### HACS

1. In HACS, open the menu → **Custom repositories**, add
   `https://github.com/ChristianHandy/HAOS_SMART_Monitor` with type
   **Integration**.
2. Install **SMART Disk Monitor** and restart Home Assistant.

### Manual

Copy `custom_components/smart_monitor` into the `custom_components` folder
of your Home Assistant configuration and restart Home Assistant.

## Configuration

1. Go to **Settings → Devices & services → Add integration** and pick
   **SMART Disk Monitor**.
2. Enter the host, SSH port, user name and a password or a private key
   (paste the whole key, starting with `-----BEGIN`).
3. Compare the host key fingerprint with the one on the host and confirm it:

   ```bash
   ssh-keygen -lf /etc/ssh/ssh_host_ed25519_key.pub
   ```

Add the integration once per host.

### Options

| Option | Default | Description |
|---|---|---|
| Do not wake up sleeping disks | On | Keeps the last values of disks in standby instead of spinning them up. |
| Devices | Empty | Disks to read instead of discovering them, one per line: a device path, optionally followed by a smartctl device type, for example `/dev/bus/0 megaraid,3` or `/dev/sg0 cciss,1`. |

SMART data is read every 5 minutes. To read it on your own schedule, turn off
polling in the integration's system options and call
`homeassistant.update_entity` from an automation.

## Entities

Entities are created for the values a disk reports, so an NVMe SSD has no
reallocated sector sensor and a SAS disk has grown defects instead.

| Entity | Disks | Notes |
|---|---|---|
| Health | all | `passed`, `warning` (an attribute crossed its threshold, NVMe critical warning) or `failed` |
| Temperature | all | °C |
| Endurance used | SSD, NVMe, SAS SSD | % of the rated endurance |
| Power-on time, Power cycles | all | diagnostic |
| Last self-test | disks with self-tests | `passed`, `failed`, `aborted` |
| Data read / written | NVMe, SAS, SSDs that report it | diagnostic |
| Reallocated, pending and offline uncorrectable sectors, interface CRC errors | SATA | diagnostic |
| Available spare, media errors | NVMe | diagnostic |
| Grown defects, uncorrected read/write errors | SAS | diagnostic |
| Command timeouts, spin retries, unsafe shutdowns, error log entries and more | varies | diagnostic, disabled by default |
| Health problem, Bad sectors | binary sensors | `on` when there is a problem |
| Self-test running, Standby | binary sensors | diagnostic |
| Start short / long / conveyance self-test, Abort self-test | buttons | only the tests the disk supports |

## Dashboard card

The [SMART Monitor card](card/README.md) shows all disks grouped by host with
their health, temperature, wear and error counters, and can start
self-tests.

```yaml
type: custom:smart-monitor-card
title: Disks
```

## Automation examples

Notify when any disk reports a problem:

```yaml
triggers:
  - trigger: state
    entity_id:
      - binary_sensor.wdc_wd40efrx_68n32n0_health_problem
      - binary_sensor.wdc_wd40efrx_68n32n0_bad_sectors
    to: "on"
actions:
  - action: notify.mobile_app_phone
    data:
      title: Disk problem
      message: "{{ trigger.to_state.name }} on {{ device_attr(device_id(trigger.entity_id), 'name') }}"
```

Run a long self-test every month:

```yaml
triggers:
  - trigger: time
    at: "03:00:00"
conditions:
  - condition: template
    value_template: "{{ now().day == 1 }}"
actions:
  - action: button.press
    target:
      entity_id: button.wdc_wd40efrx_68n32n0_start_long_self_test
```

## Security

- The SSH host key is shown when a host is added and pinned. A different key
  later stops the integration and asks you to confirm the new key, so a
  machine pretending to be your server never receives your password.
- Credentials are stored in Home Assistant's config entry storage, like the
  credentials of every other integration.
- Use a dedicated user with sudo rights for smartctl only, see
  [Requirements](#requirements).
- Commands are run with all arguments quoted. See [SECURITY.md](SECURITY.md)
  for the full list of commands.

## Troubleshooting

**"smartctl was not found"**: install smartmontools. On some NAS systems
smartctl is in `/usr/sbin` or `/usr/local/sbin`; both are searched.

**Disks are unavailable with "Permission denied"**: log in as root, or enable
sudo as described in [Requirements](#requirements).

**"smartctl could not be run with sudo"**: sudo asked for a password. Add the
`NOPASSWD` rule shown above.

**A disk behind a RAID controller is missing**: run
`smartctl --scan-open` on the host. If the disk is not listed, add it under
**Devices** in the options, for example `/dev/sg0 cciss,0`.

**"The SSH host key changed"**: if you reinstalled the host or regenerated
its keys, open the reauthentication prompt on **Settings → Devices &
services** and confirm the new fingerprint. Otherwise investigate before
continuing.

**Download diagnostics** from the integration page when reporting a problem.

## Upgrading from 1.x

- Hosts added with 1.x ask you to re-enter the password or paste the private
  key and to confirm the host key. Key files referenced by path are no longer
  used.
- Disks are now identified by WWN or serial number (or, if a disk reports
  neither, by host and device path) instead of `/dev/sdX`, so
  entity IDs change. The old entities show as unavailable; delete them from
  **Settings → Entities**.
- Health states are now `passed`, `warning` and `failed` (were `PASSED` and
  `FAILED`). Update automations that compare them.
- The **Download SMART Report** button was removed. Use **Download
  diagnostics** on the integration page.
- The scan interval can no longer be configured; see [Options](#options).

## Development

```text
custom_components/smart_monitor/  the integration
library/                          aiosmartctl, the SSH/smartctl library on PyPI
card/                             the dashboard card
tests/                            integration tests
docs/core/                        files for the Home Assistant core submission
script/                           translation, core port and check scripts
```

```bash
pip install -r requirements_test.txt ./library
pytest                                   # integration tests
cd library && pip install -e ".[test]" && pytest   # library tests
python script/gen_translations.py        # after changing strings.json
script/run_core_checks.sh                # Home Assistant core's own checks
```

`script/run_core_checks.sh` copies the integration into a Home Assistant core
checkout and runs hassfest, ruff, codespell, prettier, yamllint, strict mypy,
pylint and pytest with 100% coverage, as core's CI does. See
[docs/CORE_SUBMISSION.md](docs/CORE_SUBMISSION.md) for the path into core.

## License

MIT, see [LICENSE](LICENSE).
