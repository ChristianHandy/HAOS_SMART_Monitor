# Getting SMART Disk Monitor into Home Assistant core

This repository is set up so the integration can be copied into Home
Assistant core unchanged. This page lists what is done, what only the
maintainer can do, and the order of the pull requests.

## Status

`script/run_core_checks.sh` runs core's own checks against the integration
inside a core checkout (2026.10.2). Both variants pass: all three platforms,
and the sensor-only variant for the first pull request.

| Check | Result |
|---|---|
| hassfest (manifest, translations, icons, config flow, quality scale, mypy config) | ✅ |
| `gen_requirements_all` | ✅ |
| ruff check and ruff format with core's configuration | ✅ |
| codespell, yamllint, prettier, JSON | ✅ |
| mypy with core's strict settings | ✅ |
| pylint with Home Assistant's plugins | ✅ |
| pytest with core's test harness (translation and lingering-task checks) | ✅ 100% coverage |

The quality scale file (`docs/core/quality_scale.yaml`) claims every rule up
to platinum except two that are still **todo**. The check script marks them
done in its throwaway checkout only, so it can validate everything else.

## What only you can do

1. **Publish the library to PyPI** (`dependency-transparency`). Core only
   accepts dependencies released on PyPI from a public repository by CI.
   1. On pypi.org, add a *pending trusted publisher* for the project
      `aiosmartctl`: owner `ChristianHandy`, repository
      `HAOS_SMART_Monitor`, workflow `release-library.yml`, environment
      `pypi`.
   2. Create the `pypi` environment in the repository settings.
   3. Push the tag `aiosmartctl-v0.1.0`. The workflow checks that the tag
      matches `__version__`, builds and publishes.

   Reviewers may ask for the library to live in its own repository. If so,
   move `library/` to `ChristianHandy/aiosmartctl` and keep the same
   workflow.

2. **Add brand images** (`brands`). Open a pull request to
   [home-assistant/brands](https://github.com/home-assistant/brands) adding
   `core_integrations/smart_monitor/icon.png` (256×256) and `icon@2x.png`
   (512×512), plus `logo.png` if you have one. Then change `brands` to
   `done` in `docs/core/quality_scale.yaml`.

3. **Test on real hardware.** Reviewers will ask whether you run the
   integration yourself. Version 2.0 has only been tested against sample
   output and a simulated SSH server; see the hardware table in the README.
   Run it at least on your own Unraid/Proxmox hosts, ideally with a SAS or
   RAID controller disk, and fix anything that differs.

4. **Sign the CLA** when the Home Assistant bot asks on your first pull
   request.

## Decide before the first pull request

- **Name and domain.** Core names integrations after the product or
  protocol. Reviewers may prefer *smartmontools* (domain `smartmontools`)
  over *SMART Disk Monitor* / `smart_monitor`. Renaming later means everyone
  sets the integration up again, so settle this in the first review. Rename
  with a search-and-replace of `smart_monitor` and the integration name.
- **Scope.** SSH plus smartctl is a single, clear scope. Keep other
  protocols, such as Redfish for iDRAC/iLO, for a separate integration.

## Pull requests, in order

New integrations may only add **one platform** in their first pull request.

1. **Core: integration with the sensor platform.**

   ```bash
   git clone https://github.com/<you>/core && cd core
   git checkout -b smart-monitor
   python /path/to/this/repo/script/port_to_core.py . --platforms sensor
   python -m script.hassfest
   python -m script.gen_requirements_all
   # add homeassistant.components.smart_monitor.* to .strict-typing
   ```

   The quality scale in the copy says `bronze`; leave it at that for a new
   integration. Fill in the core pull request template; link the docs pull
   request and the library's PyPI page.

2. **Docs:** add `source/_integrations/smart_monitor.markdown` to
   [home-assistant.io](https://github.com/home-assistant/home-assistant.io)
   from `docs/home-assistant-io/smart_monitor.markdown`, targeting the
   `next` branch.

3. **Core: binary sensor platform**, after the first one is merged:
   `--platforms sensor binary_sensor`.

4. **Core: button platform**: all platforms.

5. Raise the quality scale in the manifest as rules are reviewed (silver,
   gold, platinum).

## Things reviewers are likely to ask about

- The host key confirmation step is unusual; it exists because the
  password is sent to the host. `sftp_storage` and `asuswrt` show that SSH
  integrations are accepted.
- Entities are only created for values a disk reports, and devices of
  disks that are gone are not removed automatically, because a dead disk
  must stay visible. Users can delete them (`async_remove_config_entry_device`).
- `async_setup_entry` starts reauthentication when no host key is stored.
  In core this never happens; it exists for entries from the custom
  integration. It can be removed from the core copy if reviewers ask.

## Keeping the custom integration and core in step

Develop here, then copy with `port_to_core.py`. The script rewrites imports,
drops `# BEGIN CUSTOM-ONLY` blocks from the tests, adapts the manifest and
removes platforms that are not part of a pull request.
