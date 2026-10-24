# Security Policy

## Supported versions

Only the latest release receives security fixes.

| Version | Supported |
|---------|-----------|
| 2.x     | ✅ Yes |
| < 2.0   | ❌ No  |

## Reporting a vulnerability

**Please do not report security vulnerabilities through public GitHub issues.**

Open a [GitHub security advisory](../../security/advisories/new) instead.
Include a description, steps to reproduce, the impact and, if you have one, a
suggested fix. You can expect an acknowledgement within 48 hours and a fix or
mitigation plan within 7 days for critical issues.

## Security model

The integration logs in to your servers over SSH and runs smartctl.

### Host key verification

When a host is added, the integration fetches its SSH host key without
logging in and shows the SHA256 fingerprint. Credentials are only sent after
you confirm it. The key is stored with the config entry and every later
connection must present the same key; if it changes, the integration stops
and starts reauthentication, which shows the new fingerprint and a warning.

Versions before 2.0 accepted any host key (`AutoAddPolicy`).

### Credentials

- The password or private key is stored in Home Assistant's config entry
  storage (`/config/.storage/core.config_entries`), like the credentials of
  every other integration. Protect access to your Home Assistant files.
- Private keys must be unencrypted; use a key made for this purpose.
- The SSH agent, `~/.ssh/config` and default key files of the Home Assistant
  host are never used.
- Diagnostics remove the host, user name, password, private key, host key,
  serial numbers and WWNs.

### Least privilege

Prefer a dedicated user that may only run smartctl through sudo:

```bash
useradd -r -m -s /bin/sh ha-smart
echo 'ha-smart ALL=(root) NOPASSWD: /usr/sbin/smartctl' > /etc/sudoers.d/ha-smart
chmod 440 /etc/sudoers.d/ha-smart
```

and enable **Run smartctl with sudo**. smartctl can start and abort
self-tests, which the integration offers as buttons; it cannot write data.

### Commands run on the host

Every command runs through `sh -c` with all arguments quoted. Device paths
and types come from `smartctl --scan-open`, `lsblk`, or the **Devices**
option, which only accepts a path plus a device type made of letters, digits
and `,+_-`.

| Command | When |
|---|---|
| `hostname`, `uname -s`, `uname -r`, `cat /etc/os-release`, `/etc/unraid-version`, `pveversion` | Once at setup, to name the host |
| `smartctl --version` | Setup |
| `smartctl --scan-open --json=c` | Every update, unless devices are set |
| `lsblk -d -J -o NAME,TYPE` | When the scan finds nothing |
| `smartctl --json=c -a [-n standby] [-d TYPE] DEVICE` | Every update, per disk |
| `smartctl -t short\|long\|conveyance [-d TYPE] DEVICE` | Self-test button |
| `smartctl -X [-d TYPE] DEVICE` | Abort self-test button |

With sudo enabled, `smartctl` is run as `sudo -n smartctl`. Nothing is
written to the host.

## Security-relevant changes

| Version | Change |
|---|---|
| 2.0.0 | SSH host keys are confirmed and pinned; credentials are only sent to a confirmed host. Private keys are stored instead of read from a path. Commands are quoted. The report button that wrote files to `/config/smart_reports/` was removed. |
| 1.2.0 | Removed `ssh://` from the device registry |
| 1.0.0 | Initial release |
