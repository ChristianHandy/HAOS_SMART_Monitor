---
title: SMART Disk Monitor
description: Instructions on how to monitor the SMART health of server disks over SSH in Home Assistant.
ha_category:
  - Sensor
  - System monitor
ha_release: "2026.12"
ha_iot_class: Local Polling
ha_config_flow: true
ha_codeowners:
  - '@ChristianHandy'
ha_domain: smart_monitor
ha_platforms:
  - binary_sensor
  - button
  - diagnostics
  - sensor
ha_integration_type: hub
ha_quality_scale: bronze
---

The **SMART Disk Monitor** {% term integration %} shows the health of the disks in your servers. It logs in to a server over SSH, runs [smartmontools](https://www.smartmontools.org/) `smartctl`, and creates a {% term device %} for every disk with its health, temperature, wear, error counters and self-test results.

Use it to get a notification before a disk fails, to watch NAS temperatures, or to schedule self-tests.

## Supported devices

Any server you can log in to over SSH with smartmontools 7.0 or newer installed, for example Unraid, Proxmox VE, TrueNAS, Debian, Ubuntu, or FreeBSD. It reads:

- SATA hard disks and SSDs
- NVMe SSDs
- SAS hard disks and SSDs
- Disks behind RAID controllers that smartctl can pass commands through, such as LSI MegaRAID and Dell PERC. Disks behind HP Smart Array, Areca, 3ware, and Adaptec controllers can be added by hand.

Not every combination of controller, firmware, and operating system has been tested on real hardware. Disks behind RAID controllers and SAS disks have been tested with sample output only.

## Prerequisites

On every server:

1. Install smartmontools, for example `sudo apt install smartmontools`. Unraid and Proxmox VE include it.
2. Use the `root` user, or a user that may run smartctl with sudo without a password:

   ```bash
   echo 'ha-smart ALL=(root) NOPASSWD: /usr/sbin/smartctl' | sudo tee /etc/sudoers.d/ha-smart
   ```

{% include integrations/config_flow.md %}

{% configuration_basic %}
Host:
  description: The hostname or IP address of the server.
Port:
  description: The SSH port of the server.
Username:
  description: The user to log in as.
Password:
  description: The SSH password. Leave empty when you use a private key.
Private key:
  description: An unencrypted SSH private key in OpenSSH or PEM format. Leave empty when you use a password.
Run smartctl with sudo:
  description: Enable when the user is not root and may run smartctl with sudo without a password.
{% endconfiguration_basic %}

After you enter these, Home Assistant shows the fingerprint of the server's SSH host key. Compare it with the output of `ssh-keygen -lf /etc/ssh/ssh_host_ed25519_key.pub` on the server before you confirm. Your credentials are only sent after you confirm.

{% include integrations/option_flow.md %}

{% configuration_basic %}
Do not wake up sleeping disks:
  description: Keep the last values of disks in standby instead of spinning them up. Enabled by default.
Devices:
  description: "Disks to read instead of discovering them, one per line: a device path, optionally followed by a smartctl device type. For example `/dev/bus/0 megaraid,3` or `/dev/sg0 cciss,0`."
{% endconfiguration_basic %}

## Data updates

The integration reads all disks every 5 minutes. Disks in standby are not woken up unless you turn off **Do not wake up sleeping disks**.

## Sensors

Entities are only created for values a disk reports.

- **Health**: Passed, Warning, or Failed. Warning means an attribute crossed its threshold or an NVMe disk reports a critical warning.
- **Temperature**
- **Endurance used**: Percentage of the rated endurance an SSD has used.
- **Last self-test**: Passed, Failed, Aborted, or Unknown.
- **Power-on time**, **Power cycles**, **Data read**, **Data written**
- Error counters, depending on the disk type: reallocated, pending, and offline uncorrectable sectors; interface CRC errors; available spare and media errors (NVMe); grown defects and uncorrected read, write, and verify errors (SAS). Rarely needed counters are disabled by default.

## Binary sensors

- **Health problem**: On when the health is Warning or Failed.
- **Bad sectors**: On when the disk reports reallocated, pending, or uncorrectable sectors, grown defects, or media errors.
- **Self-test running**
- **Standby**: On while the disk sleeps and shows its last values.

## Buttons

- **Start short self-test**, **Start long self-test**, **Start conveyance self-test**: Only the tests the disk supports.
- **Abort self-test**

## Examples

### Get notified when a disk has a problem

{% raw %}

```yaml
automation:
  - alias: "Disk problem"
    triggers:
      - trigger: state
        entity_id: binary_sensor.wdc_wd40efrx_68n32n0_health_problem
        to: "on"
    actions:
      - action: notify.mobile_app_phone
        data:
          message: "{{ trigger.to_state.name }} reports a problem"
```

{% endraw %}

### Run a long self-test every month

{% raw %}

```yaml
automation:
  - alias: "Monthly disk self-test"
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

{% endraw %}

## Known limitations

- Hardware RAID volumes report no SMART data. The physical disks behind the controller are shown when the controller supports pass-through.
- Disks that report neither a serial number nor a WWN, such as some USB enclosures, are identified by their device path. If the path changes, they show up as a new device.
- A disk that is asleep or unreadable when Home Assistant starts appears once it has been read.
- Encrypted private keys are not supported.

## Troubleshooting

### smartctl was not found

Install smartmontools on the server.

### Disks are unavailable with "Permission denied"

Log in as root, or enable **Run smartctl with sudo** and allow the user to run smartctl with sudo without a password.

### A disk behind a RAID controller is missing

Run `smartctl --scan-open` on the server. If the disk is not listed, add it under **Devices** in the options.

### The SSH host key changed

If you reinstalled the server or regenerated its SSH keys, confirm the new fingerprint when Home Assistant asks you to. Otherwise, find out why the key changed before you continue.

## Removing the integration

This integration follows standard integration removal. Nothing is left on the server.

{% include integrations/remove_device_service_steps.md %}
