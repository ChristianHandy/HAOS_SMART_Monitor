# Changelog

## 2.0.0

A rewrite that prepares the integration for Home Assistant core.

### Breaking changes

- Requires Home Assistant 2026.10 or newer.
- Hosts added with 1.x must be confirmed again: Home Assistant asks for the
  password or private key and shows the SSH host key to confirm.
- Disks are identified by WWN or serial number instead of their `/dev` path,
  so all entity IDs change. Delete the old, unavailable entities.
- Health states are now `passed`, `warning` and `failed`.
- The **Download SMART Report** button was removed; use **Download
  diagnostics**. Self-test errors are shown as errors instead of persistent
  notifications.
- The scan interval is fixed at 5 minutes; disable polling and use
  `homeassistant.update_entity` for another schedule.
- The server type option was removed; the host's operating system is detected.

### New

- SAS/SCSI disks: grown defects, uncorrected read/write/verify errors,
  endurance of SAS SSDs.
- Disks behind RAID controllers (MegaRAID/PERC, and HP Smart Array, Areca,
  3ware and aacraid through the **Devices** option), found with
  `smartctl --scan-open`.
- Sleeping disks are not woken up; a **Standby** binary sensor.
- Run smartctl through `sudo -n`.
- SSH host key pinning, private keys pasted in the UI, reauthentication and
  reconfiguration flows.
- One device per host with its disks below it; disks that are gone can be
  deleted.
- Endurance used, data read and written, NVMe available spare and more.
- **Self-test running** binary sensor and an **Abort self-test** button.
- Diagnostics.
- The `aiosmartctl` library and the SMART Monitor dashboard card.

### Fixed

- Options for password and key were saved but never used.
- A smartctl message containing "failed" marked the whole disk as unreadable.
- The binary sensor platform kept listening for new disks after the
  integration was unloaded.
- Starting a self-test during a poll could break the poll, because both
  shared one SSH connection object.
