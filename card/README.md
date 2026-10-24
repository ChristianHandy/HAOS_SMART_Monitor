# SMART Monitor card

A dashboard card for the SMART Disk Monitor integration. It lists every disk
grouped by host and shows its health, temperature, wear, power-on time and
problems at a glance. Click a disk to see all SMART values and start or abort
self-tests.

It finds the integration's entities on its own; there is nothing to map.

## Installation

1. Copy `smart-monitor-card.js` to `/config/www/smart-monitor-card.js`.
2. Go to **Settings → Dashboards → ⋮ → Resources → Add resource**, enter
   `/local/smart-monitor-card.js` and choose **JavaScript module**.
3. Reload the browser, then add the **SMART Monitor** card to a dashboard.

## Configuration

```yaml
type: custom:smart-monitor-card
title: Disks              # optional
host: 0123456789abcdef    # optional: device ID of one host
show_diagnostics: false   # optional: always list every SMART value
```

All options can also be set in the visual editor.

## What it shows

- A status icon and **Passed / Warning / Failed** for every disk
- Temperature, orange from 45 °C and red from 55 °C
- Endurance used as a bar for SSDs
- **Bad sectors**, **Standby** and **Self-test running** labels
- When opened: power-on time, error counters (red when not zero), the last
  self-test and self-test buttons

## Development

Open `demo.html` through a local web server, for example
`python3 -m http.server --directory card`, to see the card with made-up data
without Home Assistant.

Core integrations cannot ship dashboard cards, so the card is separate from
the integration. It can be published as its own HACS dashboard repository.
