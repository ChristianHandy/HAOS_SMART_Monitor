# Security Policy

## Supported Versions

Only the latest release receives security fixes. Please update to the latest version before reporting a vulnerability.

| Version | Supported |
|---------|-----------|
| 1.2.x   | ✅ Yes |
| < 1.2   | ❌ No  |

---

## Reporting a Vulnerability

**Please do not report security vulnerabilities through public GitHub issues.**

Instead, open a [GitHub Security Advisory](../../security/advisories/new) or send a private message to the repository owner. Include as much detail as possible:

- A description of the vulnerability
- Steps to reproduce
- Potential impact
- Suggested fix (if any)

You can expect an acknowledgement within **48 hours** and a fix or mitigation plan within **7 days** for critical issues.

---

## Security Considerations

This integration connects Home Assistant to remote machines over SSH. Understanding the security model helps you deploy it safely.

### SSH Credentials

- Credentials (username, password, or SSH key path) are stored in Home Assistant's config entry storage at `/config/.storage/core.config_entries`
- This file is readable by anyone with access to your HA filesystem — **secure your HA instance accordingly**
- Prefer **SSH key authentication** over passwords where possible
- Use a **dedicated low-privilege user** with only the permissions needed (see below) rather than `root`

### Principle of Least Privilege

The integration only needs to run `smartctl` on the remote machine. You can lock it down to exactly that:

```bash
# Create a dedicated user
useradd -r -s /bin/bash ha-smart

# Allow only smartctl — nothing else
echo 'ha-smart ALL=(ALL) NOPASSWD: /usr/sbin/smartctl' > /etc/sudoers.d/ha-smart
chmod 440 /etc/sudoers.d/ha-smart

# Add to disk group (alternative to sudo on some systems)
usermod -aG disk ha-smart
```

Use `ha-smart` as the username in the HA integration config instead of `root`.

### SSH Key Hardening

If using key-based authentication, restrict what the key can do on the server side:

```
# ~/.ssh/authorized_keys on the remote server
restrict,command="/usr/sbin/smartctl" ssh-ed25519 AAAA... home-assistant
```

> Note: The `command=` restriction limits the key to a single command. This is the most secure option but means the integration cannot run `lsblk` to auto-discover disks — you would need to manually specify devices. For most home users the disk group + sudo approach is a reasonable balance.

### What the Integration Does Over SSH

The integration executes only these commands on the remote machine:

| Command | Purpose |
|---|---|
| `lsblk -d -o NAME,TYPE --json` | Discover block devices |
| `smartctl -a --json=c /dev/sdX` | Read SMART data |
| `smartctl -a /dev/sdX` | Fallback text read |
| `smartctl -t short\|long\|conveyance /dev/sdX` | Start a self-test (button press only) |
| `smartctl -x /dev/sdX` | Full report (button press only) |
| `which smartctl` | Locate smartctl binary |

No files are written to the remote machine. No other commands are executed.

### Network Security

- All communication is encrypted via SSH
- The integration uses `paramiko` and accepts the remote host key on first connection (`AutoAddPolicy`) — this is convenient but means the first connection is vulnerable to a man-in-the-middle attack on untrusted networks
- For production use on untrusted networks, manually add the host key to your HA `known_hosts` file and switch to `RejectPolicy`

### Report Saved to Disk

When the **Download SMART Report** button is pressed, the full `smartctl -x` output is saved to `/config/smart_reports/` inside the HA container. These files may contain:

- Disk serial numbers
- Firmware versions
- Full SMART attribute history

Treat these files as sensitive and do not share them publicly. The `/config/smart_reports/` directory is not exposed by default but is accessible via the HA file editor and Samba shares if those are enabled.

---

## Known Limitations

- **Host key verification** is currently set to `AutoAddPolicy` (trust on first connect). A future version will support strict host key checking.
- **Credentials are stored in plaintext** within HA's config storage. This is consistent with how all HA integrations store credentials and is protected by HA's overall security model.
- The integration has **no rate limiting** on button presses — running a long self-test repeatedly could theoretically stress a degraded disk. Use the long self-test button with care on disks already showing errors.

---

## Changelog of Security-Relevant Changes

| Version | Change |
|---|---|
| 1.2.0 | Removed `ssh://` from device registry (was rejected by HA, no security impact) |
| 1.1.x | Fixed `via_device` references that caused silent entity registration failures |
| 1.0.0 | Initial release |# Security Policy

## Supported Versions

| Version | Supported          |
| ------- | ------------------ |
| = 1.2.0   | :white_check_mark: 
| < 1.1.9   | :x:                |

## Reporting a Vulnerability

