/*
 * SMART Monitor card for Home Assistant.
 *
 * Shows every disk of the SMART Disk Monitor integration, grouped by host,
 * with its health, temperature, wear and error counters. No build step:
 * add this file as a dashboard resource (type "module").
 *
 *   type: custom:smart-monitor-card
 *   title: Disks           # optional
 *   host: <device id>      # optional, only show the disks of one host
 *   show_diagnostics: true # optional, list every SMART value per disk
 */

const VERSION = "1.0.0";
const PLATFORM = "smart_monitor";

// Keys are the integration's entity translation keys.
const HEALTH = {
  passed: { label: "Passed", color: "var(--success-color, #43a047)", icon: "mdi:check-circle" },
  warning: { label: "Warning", color: "var(--warning-color, #ffa000)", icon: "mdi:alert" },
  failed: { label: "Failed", color: "var(--error-color, #db4437)", icon: "mdi:close-octagon" },
};

const DETAIL_KEYS = [
  ["power_on_hours", "Power-on time"],
  ["power_cycles", "Power cycles"],
  ["data_written", "Data written"],
  ["data_read", "Data read"],
  ["available_spare", "Available spare"],
  ["reallocated_sectors", "Reallocated sectors"],
  ["pending_sectors", "Pending sectors"],
  ["offline_uncorrectable", "Offline uncorrectable"],
  ["grown_defects", "Grown defects"],
  ["media_errors", "Media errors"],
  ["udma_crc_errors", "Interface CRC errors"],
  ["uncorrected_read_errors", "Uncorrected read errors"],
  ["uncorrected_write_errors", "Uncorrected write errors"],
  ["uncorrected_verify_errors", "Uncorrected verify errors"],
  ["reported_uncorrectable", "Reported uncorrectable"],
  ["command_timeouts", "Command timeouts"],
  ["unsafe_shutdowns", "Unsafe shutdowns"],
  ["error_log_entries", "Error log entries"],
  ["last_self_test", "Last self-test"],
];

const ERROR_KEYS = new Set([
  "reallocated_sectors",
  "pending_sectors",
  "offline_uncorrectable",
  "grown_defects",
  "media_errors",
  "uncorrected_read_errors",
  "uncorrected_write_errors",
]);

const escape = (value) =>
  String(value ?? "").replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" })[c]);

const usable = (state) => state && !["unknown", "unavailable"].includes(state.state);

function formatDuration(hours) {
  const value = Number(hours);
  if (!Number.isFinite(value)) return "–";
  if (value < 48) return `${Math.round(value)} h`;
  const days = value / 24;
  if (days < 365) return `${Math.round(days)} d`;
  return `${(days / 365).toFixed(1)} y`;
}

class SmartMonitorCard extends HTMLElement {
  static getConfigElement() {
    return document.createElement("smart-monitor-card-editor");
  }

  static getStubConfig() {
    return { title: "Disks" };
  }

  setConfig(config) {
    if (!config || typeof config !== "object") throw new Error("Invalid configuration");
    this._config = { show_diagnostics: false, ...config };
    this._expanded ??= new Set();
    this._signature = undefined;
    if (this._hass) this._render();
  }

  set hass(hass) {
    this._hass = hass;
    // Only re-render when one of our entities changed.
    const signature = this._entities()
      .map((id) => `${id}:${hass.states[id]?.state}:${hass.states[id]?.last_updated}`)
      .join("|");
    if (signature === this._signature) return;
    this._signature = signature;
    this._render();
  }

  getCardSize() {
    return 1 + this._disks().length * 2;
  }

  getGridOptions() {
    return { columns: 12, min_columns: 6 };
  }

  _entities() {
    const entities = this._hass?.entities ?? {};
    return Object.keys(entities).filter((id) => entities[id].platform === PLATFORM);
  }

  _disks() {
    const hass = this._hass;
    if (!hass) return [];
    const disks = new Map();
    for (const entityId of this._entities()) {
      const entry = hass.entities[entityId];
      const device = hass.devices?.[entry.device_id];
      if (!device || !device.via_device_id) continue; // the host device itself
      if (this._config.host && device.via_device_id !== this._config.host) continue;
      const state = hass.states[entityId];
      let key = entry.translation_key;
      if (!key && state?.attributes.device_class === "temperature") key = "temperature";
      if (!key) continue;
      const domain = entityId.split(".", 1)[0];
      if (!disks.has(device.id)) {
        disks.set(device.id, { device, host: hass.devices[device.via_device_id], entities: {} });
      }
      disks.get(device.id).entities[`${domain}.${key}`] = entityId;
    }
    return [...disks.values()].sort(
      (a, b) =>
        (a.host?.name_by_user || a.host?.name || "").localeCompare(b.host?.name_by_user || b.host?.name || "") ||
        (a.device.name_by_user || a.device.name || "").localeCompare(b.device.name_by_user || b.device.name || ""),
    );
  }

  _state(disk, key) {
    const entityId = disk.entities[key];
    return entityId ? this._hass.states[entityId] : undefined;
  }

  _format(disk, key) {
    const state = this._state(disk, key);
    if (!usable(state)) return undefined;
    if (key === "sensor.power_on_hours") return formatDuration(state.state);
    if (key === "sensor.last_self_test") {
      return this._hass.formatEntityState?.(state) ?? state.state;
    }
    return this._hass.formatEntityState?.(state) ?? `${state.state} ${state.attributes.unit_of_measurement ?? ""}`;
  }

  _render() {
    if (!this._config || !this._hass) return;
    if (!this.shadowRoot) this.attachShadow({ mode: "open" });

    const disks = this._disks();
    let lastHost;
    const rows = disks
      .map((disk) => {
        const hostName = disk.host?.name_by_user || disk.host?.name || "";
        const header =
          hostName !== lastHost && !this._config.host
            ? `<div class="host"><ha-icon icon="mdi:server"></ha-icon>${escape(hostName)}</div>`
            : "";
        lastHost = hostName;
        return header + this._renderDisk(disk);
      })
      .join("");

    const failing = disks.filter((disk) => ["failed", "warning"].includes(this._state(disk, "sensor.health")?.state)).length;
    const title = this._config.title ?? "";

    this.shadowRoot.innerHTML = `
      <style>${STYLE}</style>
      <ha-card>
        ${
          title || disks.length
            ? `<div class="header">
                 <span class="title">${escape(title)}</span>
                 <span class="summary ${failing ? "bad" : ""}">
                   ${failing ? `${failing} of ${disks.length} need attention` : `${disks.length} disks healthy`}
                 </span>
               </div>`
            : ""
        }
        <div class="disks">
          ${rows || `<div class="empty">No disks from the SMART Disk Monitor integration were found.</div>`}
        </div>
      </ha-card>`;

    this.shadowRoot.querySelectorAll("[data-more-info]").forEach((element) =>
      element.addEventListener("click", (event) => {
        event.stopPropagation();
        this.dispatchEvent(
          new CustomEvent("hass-more-info", {
            bubbles: true,
            composed: true,
            detail: { entityId: element.dataset.moreInfo },
          }),
        );
      }),
    );
    this.shadowRoot.querySelectorAll("[data-toggle]").forEach((element) =>
      element.addEventListener("click", () => {
        const id = element.dataset.toggle;
        if (this._expanded.has(id)) this._expanded.delete(id);
        else this._expanded.add(id);
        this._signature = undefined;
        this._render();
      }),
    );
    this.shadowRoot.querySelectorAll("[data-press]").forEach((element) =>
      element.addEventListener("click", (event) => {
        event.stopPropagation();
        this._hass.callService("button", "press", { entity_id: element.dataset.press });
      }),
    );
  }

  _renderDisk(disk) {
    const { device } = disk;
    const health = this._state(disk, "sensor.health");
    const healthInfo = HEALTH[health?.state] ?? {
      label: health?.state === "unavailable" ? "Unavailable" : "Unknown",
      color: "var(--disabled-text-color, #9e9e9e)",
      icon: "mdi:help-circle",
    };
    const temperature = this._format(disk, "sensor.temperature");
    const temperatureValue = Number(this._state(disk, "sensor.temperature")?.state);
    const used = Number(this._state(disk, "sensor.percentage_used")?.state);
    const standby = this._state(disk, "binary_sensor.standby")?.state === "on";
    const testing = this._state(disk, "binary_sensor.self_test_running")?.state === "on";
    const badSectors = this._state(disk, "binary_sensor.sector_problem")?.state === "on";
    const powerOn = this._format(disk, "sensor.power_on_hours");
    const expanded = this._config.show_diagnostics || this._expanded.has(device.id);

    const chips = [
      standby && `<span class="chip"><ha-icon icon="mdi:sleep"></ha-icon>Standby</span>`,
      testing && `<span class="chip"><ha-icon icon="mdi:clipboard-play-outline"></ha-icon>Self-test running</span>`,
      badSectors && `<span class="chip bad"><ha-icon icon="mdi:alert-circle"></ha-icon>Bad sectors</span>`,
    ]
      .filter(Boolean)
      .join("");

    const tempClass = temperatureValue >= 55 ? "bad" : temperatureValue >= 45 ? "warn" : "";
    const wear = Number.isFinite(used)
      ? `<div class="wear" title="Endurance used">
           <div class="bar"><div style="width:${Math.min(100, Math.max(0, used))}%;background:${
             used >= 90 ? "var(--error-color, #db4437)" : used >= 70 ? "var(--warning-color, #ffa000)" : "var(--primary-color)"
           }"></div></div>
           <span>${Math.round(used)}% used</span>
         </div>`
      : "";

    return `
      <div class="disk" data-toggle="${escape(device.id)}">
        <div class="status" style="color:${healthInfo.color}" ${
          health ? `data-more-info="${escape(health.entity_id)}"` : ""
        } title="${escape(healthInfo.label)}">
          <ha-icon icon="${healthInfo.icon}"></ha-icon>
        </div>
        <div class="main">
          <div class="name">${escape(device.name_by_user || device.name)}</div>
          <div class="meta">
            <span style="color:${healthInfo.color}">${escape(healthInfo.label)}</span>
            ${device.manufacturer ? `· ${escape(device.manufacturer)}` : ""}
            ${powerOn ? `· ${escape(powerOn)} on` : ""}
          </div>
          ${chips ? `<div class="chips">${chips}</div>` : ""}
          ${wear}
        </div>
        <div class="temperature ${tempClass}" ${
          disk.entities["sensor.temperature"] ? `data-more-info="${escape(disk.entities["sensor.temperature"])}"` : ""
        }>${temperature ? escape(temperature) : ""}</div>
        <ha-icon class="chevron" icon="${expanded ? "mdi:chevron-up" : "mdi:chevron-down"}"></ha-icon>
      </div>
      ${expanded ? this._renderDetails(disk) : ""}`;
  }

  _renderDetails(disk) {
    const rows = DETAIL_KEYS.map(([key, label]) => {
      const fullKey = `sensor.${key}`;
      const value = this._format(disk, fullKey);
      if (value === undefined) return "";
      const raw = Number(this._state(disk, fullKey)?.state);
      const bad = ERROR_KEYS.has(key) && raw > 0;
      return `<div class="detail ${bad ? "bad" : ""}" data-more-info="${escape(disk.entities[fullKey])}">
                <span>${label}</span><span>${escape(value)}</span>
              </div>`;
    }).join("");

    const buttons = [
      ["button.self_test_short", "Short test", "mdi:play-circle-outline"],
      ["button.self_test_long", "Long test", "mdi:play-circle"],
      ["button.abort_self_test", "Abort", "mdi:stop-circle-outline"],
    ]
      .filter(([key]) => usable(this._state(disk, key)) || this._state(disk, key)?.state === "unknown")
      .map(
        ([key, label, icon]) =>
          `<button data-press="${escape(disk.entities[key])}"><ha-icon icon="${icon}"></ha-icon>${label}</button>`,
      )
      .join("");

    return `<div class="details">${rows}${buttons ? `<div class="actions">${buttons}</div>` : ""}</div>`;
  }
}

const STYLE = `
  ha-card { overflow: hidden; }
  .header { display: flex; align-items: baseline; justify-content: space-between; gap: 8px; padding: 16px 16px 4px; }
  .title { font-size: var(--ha-card-header-font-size, 1.25rem); font-weight: 500; }
  .summary { color: var(--secondary-text-color); font-size: 0.875rem; }
  .summary.bad { color: var(--error-color, #db4437); font-weight: 500; }
  .disks { padding: 4px 0 8px; }
  .host { display: flex; align-items: center; gap: 8px; padding: 12px 16px 4px; color: var(--secondary-text-color);
          font-size: 0.75rem; font-weight: 500; text-transform: uppercase; letter-spacing: 0.04em; }
  .host ha-icon { --mdc-icon-size: 16px; }
  .disk { display: grid; grid-template-columns: 40px 1fr auto 24px; align-items: center; gap: 12px;
          padding: 8px 16px; cursor: pointer; }
  .disk:hover { background: var(--secondary-background-color); }
  .status ha-icon { --mdc-icon-size: 32px; }
  .main { min-width: 0; }
  .name { font-weight: 500; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
  .meta { color: var(--secondary-text-color); font-size: 0.8125rem; }
  .chips { display: flex; flex-wrap: wrap; gap: 4px; margin-top: 4px; }
  .chip { display: inline-flex; align-items: center; gap: 4px; padding: 1px 8px; border-radius: 12px; font-size: 0.75rem;
          background: var(--secondary-background-color); color: var(--secondary-text-color); }
  .chip ha-icon { --mdc-icon-size: 14px; }
  .chip.bad { background: color-mix(in srgb, var(--error-color, #db4437) 15%, transparent); color: var(--error-color, #db4437); }
  .wear { display: flex; align-items: center; gap: 8px; margin-top: 6px; font-size: 0.75rem; color: var(--secondary-text-color); }
  .bar { flex: 1; max-width: 160px; height: 6px; border-radius: 3px; background: var(--divider-color); overflow: hidden; }
  .bar > div { height: 100%; border-radius: 3px; }
  .temperature { font-size: 1.125rem; font-weight: 500; white-space: nowrap; }
  .temperature.warn { color: var(--warning-color, #ffa000); }
  .temperature.bad { color: var(--error-color, #db4437); }
  .chevron { color: var(--secondary-text-color); }
  .details { padding: 0 16px 12px 68px; display: grid; grid-template-columns: repeat(auto-fill, minmax(200px, 1fr)); gap: 2px 16px; }
  .detail { display: flex; justify-content: space-between; gap: 8px; font-size: 0.8125rem; padding: 3px 0; cursor: pointer;
            border-bottom: 1px solid var(--divider-color); }
  .detail span:first-child { color: var(--secondary-text-color); }
  .detail.bad span:last-child { color: var(--error-color, #db4437); font-weight: 500; }
  .actions { grid-column: 1 / -1; display: flex; flex-wrap: wrap; gap: 8px; padding-top: 8px; }
  button { display: inline-flex; align-items: center; gap: 4px; font: inherit; font-size: 0.8125rem; cursor: pointer;
           padding: 4px 12px; border-radius: 16px; border: 1px solid var(--divider-color);
           background: none; color: var(--primary-color); }
  button:hover { background: var(--secondary-background-color); }
  button ha-icon { --mdc-icon-size: 16px; }
  .empty { padding: 16px; color: var(--secondary-text-color); }
  @media (max-width: 450px) { .details { padding-left: 16px; } }
`;

class SmartMonitorCardEditor extends HTMLElement {
  setConfig(config) {
    this._config = config;
    this._render();
  }

  set hass(hass) {
    this._hass = hass;
    this._render();
  }

  _render() {
    if (!this._hass || !this._config) return;
    if (!this._form) {
      this._form = document.createElement("ha-form");
      this._form.computeLabel = (schema) =>
        ({ title: "Title", host: "Only show disks of this host", show_diagnostics: "Always show all SMART values" })[
          schema.name
        ];
      this._form.addEventListener("value-changed", (event) => {
        const config = { ...event.detail.value };
        for (const key of Object.keys(config)) if (config[key] === "" || config[key] === undefined) delete config[key];
        this.dispatchEvent(new CustomEvent("config-changed", { detail: { config }, bubbles: true, composed: true }));
      });
      this.appendChild(this._form);
    }
    this._form.hass = this._hass;
    this._form.data = this._config;
    this._form.schema = [
      { name: "title", selector: { text: {} } },
      { name: "host", selector: { device: { integration: PLATFORM } } },
      { name: "show_diagnostics", selector: { boolean: {} } },
    ];
  }
}

customElements.define("smart-monitor-card", SmartMonitorCard);
customElements.define("smart-monitor-card-editor", SmartMonitorCardEditor);

window.customCards = window.customCards || [];
window.customCards.push({
  type: "smart-monitor-card",
  name: "SMART Monitor",
  description: "Health, temperature and wear of the disks of the SMART Disk Monitor integration.",
  preview: true,
  documentationURL: "https://github.com/ChristianHandy/HAOS_SMART_Monitor/tree/main/card",
});

console.info(`%c SMART-MONITOR-CARD %c ${VERSION} `, "color:white;background:#03a9f4;font-weight:700", "color:#03a9f4");
