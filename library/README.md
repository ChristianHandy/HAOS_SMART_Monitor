# aiosmartctl

Asynchronous Python client that reads SMART disk health from remote hosts by
running [smartmontools](https://www.smartmontools.org/) `smartctl` over SSH.
It powers the SMART Disk Monitor integration for Home Assistant.

- SATA/ATA hard disks and SSDs, NVMe, and SAS/SCSI disks
- Disks behind RAID controllers and HBAs that smartctl can pass through
  (MegaRAID/PERC, HP Smart Array `cciss`, Areca, 3ware, aacraid) and USB bridges
- Discovery with `smartctl --scan-open`, falling back to `lsblk`
- Does not wake disks in standby unless asked to
- Optional `sudo -n` for non-root users
- SSH host key pinning, password or private key authentication
- Falls back to text parsing for smartctl 6.x, which has no JSON output

## Usage

```python
import asyncio

from aiosmartctl import SmartctlClient, fetch_host_key, host_key_fingerprint


async def main() -> None:
    host_key = await fetch_host_key("nas.local")
    print("Trust this host key?", host_key_fingerprint(host_key))

    client = SmartctlClient(
        "nas.local",
        username="root",
        password="secret",
        known_host_key=host_key,
    )
    async with client.session() as session:
        for disk in await session.get_disks():
            print(disk.spec.key, disk.model, disk.health, disk.temperature)


asyncio.run(main())
```

Disks the controller hides from `--scan-open`, such as disks behind an HP
Smart Array, can be read by passing device specifications explicitly:

```python
from aiosmartctl import DeviceSpec

specs = [DeviceSpec.parse("/dev/sg0 cciss,0"), DeviceSpec.parse("/dev/sg0 cciss,1")]
disks = await session.get_disks(specs)
```

## Hardware test status

The parsers are tested against smartctl 7.x JSON output for each disk
family, and the SSH layer against an in-process SSH server. Not every
combination has been tested against real hardware. In particular, SAS disks,
RAID controller pass-through (MegaRAID, cciss, Areca, 3ware, aacraid),
FreeBSD/TrueNAS CORE hosts and smartctl 6.x have only been checked against
sample output. Reports and `smartctl --json -a` captures from such systems
are welcome.

## Development

```bash
pip install -e ".[test]"
pytest --cov
```

## License

MIT
