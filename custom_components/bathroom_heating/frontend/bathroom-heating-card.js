/* Fürdőszoba fűtés – Lovelace kártya (bathroom_heating integráció)
 * Konfiguráció:
 *   type: custom:bathroom-heating-card
 *   entity: sensor.furdoszoba_allapot   # az integráció "Állapot" szenzora
 *   title: Fürdőszoba                   # opcionális
 */
const CARD_VERSION = "1.0.0";

const MODES = [
  ["auto", "Automatikus", "mdi:calendar-sync"],
  ["comfort", "Komfort", "mdi:sun-thermometer"],
  ["eco", "Takarékos", "mdi:leaf"],
  ["away", "Távol", "mdi:home-export-outline"],
  ["off", "Ki", "mdi:power"],
];
const PERIODS = [
  ["day", "Ma", "tegnap"],
  ["week", "Hét", "előző hét"],
  ["month", "Hónap", "előző hónap"],
  ["year", "Év", "tavaly"],
];
const SETTINGS = [
  ["comfort_temp", "Fürdéskor"],
  ["eco_temp", "Egyébként"],
  ["towel_min_temp", "Törölköző, ha hidegebb mint"],
  ["battery_on", "Törölköző, ha az akku legalább", "has_battery"],
  ["towel_before", "Törölköző fürdés előtt"],
  ["towel_after", "Törölköző fürdés után"],
  ["humidity_limit", "Szellőztetés e pára felett"],
  ["return_limit", "Visszatérő víz (padló kész)"],
  ["bath_duration", "„Fürdés most” hossza"],
  ["price", "Áramár"],
];

const fmtNum = (v, d = 1) =>
  v === null || v === undefined || isNaN(v)
    ? "–"
    : Number(v).toLocaleString("hu-HU", { minimumFractionDigits: d, maximumFractionDigits: d });
const hhmm = (iso) => {
  if (!iso) return "";
  const d = new Date(iso);
  return d.toLocaleTimeString("hu-HU", { hour: "2-digit", minute: "2-digit" });
};
const dayWord = (iso) => {
  if (!iso) return "";
  const d = new Date(iso);
  const t = new Date();
  const diff = Math.round(
    (new Date(d.getFullYear(), d.getMonth(), d.getDate()) -
      new Date(t.getFullYear(), t.getMonth(), t.getDate())) / 86400000
  );
  return diff === 0 ? "ma" : diff === 1 ? "holnap" : d.toLocaleDateString("hu-HU", { weekday: "long" });
};
const esc = (s) =>
  String(s ?? "").replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
const parseSchedule = (txt) =>
  String(txt || "")
    .split(/[;,]/)
    .map((p) => p.trim())
    .filter((p) => /^\d{1,2}:\d{2}\s*-\s*\d{1,2}:\d{2}$/.test(p))
    .map((p) => p.split("-").map((x) => x.trim().padStart(5, "0")));
const toMin = (s) => {
  const [h, m] = s.split(":").map(Number);
  return h * 60 + m;
};

class BathroomHeatingCard extends HTMLElement {
  constructor() {
    super();
    this._ui = { period: "day", settings: false };
    this.attachShadow({ mode: "open" });
  }

  static getConfigElement() {
    return document.createElement("bathroom-heating-card-editor");
  }

  static getStubConfig(hass) {
    const ent = Object.values(hass.states).find(
      (s) => s.attributes && s.attributes.integration === "bathroom_heating"
    );
    return { entity: ent ? ent.entity_id : "" };
  }

  setConfig(config) {
    if (!config || !config.entity) throw new Error("Add meg az 'entity'-t: az integráció Állapot szenzorát.");
    this._config = config;
    this._sig = null;
  }

  getCardSize() {
    return 8;
  }

  getGridOptions() {
    return { columns: 12, min_columns: 6, rows: "auto" };
  }

  set hass(hass) {
    this._hass = hass;
    const st = hass.states[this._config.entity];
    const ents = (st && st.attributes.entities) || {};
    const sig = [st && st.last_updated, st && st.state]
      .concat(Object.values(ents).map((e) => hass.states[e] && hass.states[e].state))
      .join("|");
    if (sig === this._sig) return;
    // do not re-render under the user's fingers while editing a setting
    const active = this.shadowRoot.activeElement;
    if (active && (active.tagName === "INPUT" || active.tagName === "SELECT")) return;
    this._sig = sig;
    this._render();
  }

  // ---------------------------------------------------------------- helpers
  get _a() {
    const st = this._hass.states[this._config.entity];
    return st ? st.attributes : null;
  }
  _eid(key) {
    return (this._a.entities || {})[key];
  }
  _call(domain, service, key, data = {}) {
    const entity_id = this._eid(key);
    if (!entity_id) return;
    this._hass.callService(domain, service, { entity_id, ...data });
  }
  _more(key) {
    const entityId = this._eid(key) || this._config.entity;
    const ev = new Event("hass-more-info", { bubbles: true, composed: true });
    ev.detail = { entityId };
    this.dispatchEvent(ev);
  }

  // ---------------------------------------------------------------- timeline
  _timeline(a) {
    const s = a.settings || {};
    const now = new Date();
    const weekend = now.getDay() === 0 || now.getDay() === 6;
    const wins = parseSchedule(weekend ? s.schedule_weekend : s.schedule_weekday).map(([x, y]) => {
      let e = toMin(y);
      const b = toMin(x);
      if (e <= b) e = 1440;
      return [b, e];
    });
    if (a.manual_bath_until) {
      const e = new Date(a.manual_bath_until);
      const end = e.getHours() * 60 + e.getMinutes();
      const start = Math.max(0, end - (s.bath_duration || 45));
      wins.push([start, end < start ? 1440 : end]);
    }
    const nowMin = now.getHours() * 60 + now.getMinutes();
    const pct = (m) => `${Math.max(0, Math.min(100, (m / 1440) * 100)).toFixed(2)}%`;
    const seg = (b, e, cls, title) =>
      e > b ? `<i class="seg ${cls}" style="left:${pct(b)};width:${pct(e - b)}" title="${esc(title)}"></i>` : "";
    let html = "";
    // preheat ramp of the next bath (only if it is today)
    if (a.preheat_start && a.next_bath_start && dayWord(a.next_bath_start) === "ma") {
      const p = new Date(a.preheat_start);
      const n = new Date(a.next_bath_start);
      const pb = dayWord(a.preheat_start) === "ma" ? p.getHours() * 60 + p.getMinutes() : 0;
      html += seg(pb, n.getHours() * 60 + n.getMinutes(), "pre", "Előfűtés");
    }
    for (const [b, e] of wins) {
      html += seg(b - (s.towel_before || 0), b, "towel", "Törölközőszárító fürdés előtt");
      html += seg(e, e + (s.towel_after || 0), "towel", "Törölközőszárító fürdés után");
      html += seg(b, e, "bath", "Fürdés");
    }
    const labels = wins
      .filter(([b]) => b < 1440)
      .map(
        ([b]) =>
          `<span class="tl-label" style="left:${pct(b)}">${String(Math.floor(b / 60)).padStart(2, "0")}:${String(b % 60).padStart(2, "0")}</span>`
      )
      .join("");
    return `
      <div class="timeline" role="img" aria-label="Mai fürdési idők és fűtés">
        <div class="tl-track">${html}<b class="now" style="left:${pct(nowMin)}"></b></div>
        <div class="tl-labels">${labels}</div>
        <div class="tl-hours"><span>0</span><span>6</span><span>12</span><span>18</span><span>24</span></div>
      </div>`;
  }

  // ---------------------------------------------------------------- render
  _render() {
    const hass = this._hass;
    const a = this._a;
    const root = this.shadowRoot;
    if (!a) {
      root.innerHTML = `<ha-card><div class="empty">A(z) ${esc(this._config.entity)} entitás nem található.</div></ha-card>`;
      return;
    }
    const st = hass.states[this._config.entity];
    const title = this._config.title || "Fürdőszoba";
    const t = a.room_temp;
    const target = a.floor_target;
    const rh = a.humidity;
    const vent = a.ventilation_needed;
    const humidClass = rh >= (a.settings?.humidity_limit ?? 65) ? "hi" : rh >= 60 ? "mid" : "ok";
    const statusClass = a.bath_active
      ? "bath"
      : a.preheat_active
      ? "pre"
      : vent
      ? "warn"
      : a.mode === "off"
      ? "off"
      : "idle";

    // floor tile
    let floorState, floorSub;
    if (a.mode === "off") [floorState, floorSub] = ["Ki", "kézi vezérlés"];
    else if (!a.floor_demand) [floorState, floorSub] = ["Pihen", a.floor_reason || ""];
    else if (a.house_heating) [floorState, floorSub] = ["Fűt", "a ház fűtésével együtt"];
    else if (a.boiler_request) [floorState, floorSub] = ["Fűt", "kazán a padlóra"];
    else [floorState, floorSub] = ["Kering", "a padló elég meleg"];
    const ret =
      a.return_temp !== null && a.return_temp !== undefined
        ? `<span class="chip">visszatérő ${fmtNum(a.return_temp)}° / ${fmtNum(a.settings?.return_limit, 0)}°</span>`
        : "";

    // towel tile
    const towelOn = a.towel_on;
    const watt =
      a.towel_power !== null && a.towel_power !== undefined && towelOn
        ? `<span class="chip">${fmtNum(a.towel_power, 0)} W</span>`
        : "";
    const bat =
      a.battery !== null && a.battery !== undefined ? `<span class="chip">akku ${fmtNum(a.battery, 0)}%</span>` : "";

    // next bath line
    let next = "";
    if (a.bath_active) {
      next = a.manual_bath_until ? `Fürdés ${hhmm(a.manual_bath_until)}-ig` : "Fürdés folyamatban";
    } else if (a.next_bath_start) {
      next = `Következő fürdés: ${dayWord(a.next_bath_start)} ${hhmm(a.next_bath_start)}`;
      if (a.preheat_active) next += " · előfűtés fut";
      else if (a.preheat_start && a.mode === "auto") next += ` · előfűtés ${hhmm(a.preheat_start)}-tól`;
    }

    // energy
    const en = (a.energy || {})[this._ui.period] || {};
    const per = PERIODS.find((p) => p[0] === this._ui.period);
    const tabs = PERIODS.map(
      ([k, l]) =>
        `<button class="tab ${k === this._ui.period ? "on" : ""}" data-period="${k}" aria-pressed="${k === this._ui.period}">${l}</button>`
    ).join("");

    const modeBtns = MODES.map(
      ([k, l, icon]) =>
        `<button class="mode ${a.mode === k ? "on" : ""}" data-mode="${l}" aria-pressed="${a.mode === k}">
           <ha-icon icon="${icon}"></ha-icon><span>${l}</span></button>`
    ).join("");

    const mold = a.mold_risk || "";
    const moldClass = mold === "magas" ? "hi" : mold === "közepes" ? "mid" : "ok";

    root.innerHTML = `
      <style>${STYLE}</style>
      <ha-card>
        <header>
          <h2>${esc(title)}</h2>
          <button class="status ${statusClass}" data-more="status">${esc(st.state)}</button>
        </header>

        <section class="hero">
          <div class="temp">
            <span class="big">${fmtNum(t)}<sup>°</sup></span>
            ${target !== null && target !== undefined ? `<span class="target">cél ${fmtNum(target)}°</span>` : ""}
          </div>
          <div class="hum ${humidClass}" title="Harmatpont ${fmtNum(a.dew_point)}°">
            <ha-icon icon="mdi:water-percent"></ha-icon>
            <span class="hv">${fmtNum(rh, 0)}%</span>
            <span class="mold ${moldClass}">penész: ${esc(mold)}</span>
          </div>
        </section>

        ${this._timeline(a)}
        ${next ? `<p class="next">${esc(next)}</p>` : ""}

        ${
          vent || a.ventilation_hint
            ? `<div class="banner ${vent ? "warn" : "info"}" role="status">
                 <ha-icon icon="${a.window_open ? "mdi:window-open-variant" : "mdi:weather-windy"}"></ha-icon>
                 <span>${esc(a.ventilation_hint)}${vent ? " – nyiss ablakot 5–10 percre." : ""}</span>
               </div>`
            : ""
        }

        <section class="devices">
          <button class="dev floor ${a.floor_demand && a.mode !== "off" ? "active" : ""}" data-more="floor_target">
            <ha-icon icon="mdi:heating-coil"></ha-icon>
            <span class="dn">Padlófűtés</span>
            <span class="ds">${esc(floorState)}</span>
            <span class="dsub">${esc(floorSub)}</span>
            <span class="chips">${ret}</span>
          </button>
          <button class="dev towel ${towelOn ? "active" : ""}" data-more="towel_reason">
            <ha-icon icon="mdi:radiator"></ha-icon>
            <span class="dn">Törölközőszárító</span>
            <span class="ds">${towelOn ? "Megy" : "Ki"}</span>
            <span class="dsub">${esc(a.towel_reason || "")}</span>
            <span class="chips">${watt}${bat}</span>
          </button>
        </section>

        <section class="actions">
          ${
            a.bath_active
              ? `<button class="primary stop" data-press="bath_stop"><ha-icon icon="mdi:bathtub-outline"></ha-icon>Fürdés vége</button>`
              : `<button class="primary" data-press="bath_start"><ha-icon icon="mdi:bathtub"></ha-icon>Fürdés most</button>`
          }
          <button class="secondary ${a.towel_boost_until ? "on" : ""}" data-press="towel_boost">
            <ha-icon icon="mdi:radiator"></ha-icon>${
              a.towel_boost_until ? `${hhmm(a.towel_boost_until)}-ig`: "Törölköző 30′"
            }
          </button>
        </section>

        <nav class="modes" aria-label="Üzemmód">${modeBtns}</nav>

        <section class="energy">
          <div class="en-head">
            <h3>Törölközőszárító fogyasztás</h3>
            <div class="tabs" role="group">${tabs}</div>
          </div>
          <div class="en-vals">
            <div><span class="ev">${fmtNum(en.kwh, 2)}</span><span class="eu">kWh</span></div>
            <div><span class="ev">${Number(en.ft || 0).toLocaleString("hu-HU")}</span><span class="eu">Ft</span></div>
          </div>
          <p class="en-prev">${per[2]}: ${fmtNum(en.prev_kwh, 2)} kWh · ${Number(en.prev_ft || 0).toLocaleString("hu-HU")} Ft
            <span class="price">${fmtNum(a.price, 1)} Ft/kWh</span></p>
        </section>

        <button class="settings-toggle" aria-expanded="${this._ui.settings}">
          <ha-icon icon="mdi:cog-outline"></ha-icon>Beállítások
          <ha-icon class="chev" icon="mdi:chevron-${this._ui.settings ? "up" : "down"}"></ha-icon>
        </button>
        ${this._ui.settings ? this._settingsHtml(a) : ""}
      </ha-card>`;
    this._bind();
  }

  _settingsHtml(a) {
    const s = a.settings || {};
    const sched = (key, label) => {
      const rows = parseSchedule(s[key])
        .map(
          ([b, e], i) => `
          <div class="slot" data-key="${key}" data-i="${i}">
            <input type="time" value="${b}" aria-label="${label} kezdete" data-part="0">
            <span>–</span>
            <input type="time" value="${e}" aria-label="${label} vége" data-part="1">
            <button class="icon" data-del="${key}" data-i="${i}" aria-label="Törlés"><ha-icon icon="mdi:close"></ha-icon></button>
          </div>`
        )
        .join("");
      return `<div class="sched"><h4>${label}</h4>${rows}
        <button class="add" data-add="${key}"><ha-icon icon="mdi:plus"></ha-icon>Időpont</button></div>`;
    };
    const nums = SETTINGS.filter(([, , cond]) => !cond || a[cond])
      .map(([key, label]) => {
        const eid = this._eid(key);
        const ent = eid && this._hass.states[eid];
        if (!ent) return "";
        const at = ent.attributes;
        return `<label class="num"><span>${label}</span>
          <span class="nwrap">
            <button class="icon" data-step="${key}" data-dir="-1" aria-label="Csökkentés"><ha-icon icon="mdi:minus"></ha-icon></button>
            <input type="number" inputmode="decimal" data-num="${key}" value="${ent.state}" min="${at.min}" max="${at.max}" step="${at.step}">
            <button class="icon" data-step="${key}" data-dir="1" aria-label="Növelés"><ha-icon icon="mdi:plus"></ha-icon></button>
            <em>${esc(at.unit_of_measurement || "")}</em>
          </span></label>`;
      })
      .join("");
    return `<section class="settings">
      <div class="scheds">
        ${sched("schedule_weekday", "Hétköznap fürdés")}
        ${sched("schedule_weekend", "Hétvégén fürdés")}
      </div>
      <div class="nums">${nums}</div>
      <p class="learn">Tanult felfűtés: ${fmtNum(a.heating_rate, 2)} °C/óra – ebből számolja, mikor kell indítani a padlót.</p>
    </section>`;
  }

  _saveSchedule(key, list) {
    const txt = list
      .filter(([b, e]) => b && e && b !== e)
      .sort((x, y) => x[0].localeCompare(y[0]))
      .map(([b, e]) => `${b}-${e}`)
      .join("; ");
    this._call("text", "set_value", key, { value: txt });
  }

  _bind() {
    const r = this.shadowRoot;
    const a = this._a;
    r.querySelectorAll("[data-press]").forEach((b) =>
      b.addEventListener("click", () => {
        b.classList.add("pressed");
        this._call("button", "press", b.dataset.press);
      })
    );
    r.querySelectorAll("[data-mode]").forEach((b) =>
      b.addEventListener("click", () => this._call("select", "select_option", "mode", { option: b.dataset.mode }))
    );
    r.querySelectorAll("[data-period]").forEach((b) =>
      b.addEventListener("click", () => {
        this._ui.period = b.dataset.period;
        this._render();
      })
    );
    r.querySelectorAll("[data-more]").forEach((b) =>
      b.addEventListener("click", () => this._more(b.dataset.more))
    );
    const tog = r.querySelector(".settings-toggle");
    tog.addEventListener("click", () => {
      this._ui.settings = !this._ui.settings;
      this._render();
    });
    if (!this._ui.settings) return;

    const sched = (key) => parseSchedule(a.settings[key]);
    r.querySelectorAll(".slot input").forEach((inp) =>
      inp.addEventListener("change", () => {
        const slot = inp.closest(".slot");
        const list = sched(slot.dataset.key);
        list[+slot.dataset.i][+inp.dataset.part] = inp.value;
        inp.blur();
        this._saveSchedule(slot.dataset.key, list);
      })
    );
    r.querySelectorAll("[data-del]").forEach((b) =>
      b.addEventListener("click", (ev) => {
        ev.preventDefault();
        const list = sched(b.dataset.del);
        list.splice(+b.dataset.i, 1);
        this._saveSchedule(b.dataset.del, list);
      })
    );
    r.querySelectorAll("[data-add]").forEach((b) =>
      b.addEventListener("click", () => {
        const list = sched(b.dataset.add);
        const last = list.length ? list[list.length - 1][1] : "19:30";
        const m = Math.min(toMin(last) + 60, 23 * 60);
        const f = (x) => `${String(Math.floor(x / 60)).padStart(2, "0")}:${String(x % 60).padStart(2, "0")}`;
        list.push([f(m), f(m + 30)]);
        this._saveSchedule(b.dataset.add, list);
      })
    );
    r.querySelectorAll("[data-num]").forEach((inp) =>
      inp.addEventListener("change", () => {
        inp.blur();
        this._call("number", "set_value", inp.dataset.num, { value: Number(inp.value) });
      })
    );
    r.querySelectorAll("[data-step]").forEach((b) =>
      b.addEventListener("click", (ev) => {
        ev.preventDefault();
        const ent = this._hass.states[this._eid(b.dataset.step)];
        if (!ent) return;
        const at = ent.attributes;
        const v = Math.min(at.max, Math.max(at.min, Number(ent.state) + Number(b.dataset.dir) * at.step));
        this._call("number", "set_value", b.dataset.step, { value: Math.round(v * 100) / 100 });
      })
    );
  }
}

const STYLE = `
:host {
  --bh-floor: #f29e4c;
  --bh-towel: #e0607e;
  --bh-water: #3a9fd8;
  --bh-pre: #f6c58f;
  --bh-warn: var(--warning-color, #e6a700);
  --bh-bad: var(--error-color, #db4437);
  --bh-good: var(--success-color, #43a047);
  --bh-muted: var(--secondary-text-color);
  --bh-line: var(--divider-color, rgba(127,127,127,.25));
  --bh-soft: color-mix(in srgb, var(--primary-text-color) 6%, transparent);
}
ha-card { padding: 16px 16px 8px; overflow: hidden; }
* { box-sizing: border-box; }
button { font: inherit; color: inherit; background: none; border: 0; cursor: pointer; }
button:focus-visible, input:focus-visible { outline: 2px solid var(--primary-color); outline-offset: 2px; }
.empty { padding: 16px; color: var(--bh-muted); }

header { display: flex; align-items: center; justify-content: space-between; gap: 8px; }
h2 { margin: 0; font-size: 1.15rem; font-weight: 500; letter-spacing: .01em; }
.status { padding: 4px 10px; border-radius: 999px; font-size: .8rem; background: var(--bh-soft); color: var(--bh-muted); text-align: right; }
.status.bath { background: color-mix(in srgb, var(--bh-water) 18%, transparent); color: var(--bh-water); }
.status.pre { background: color-mix(in srgb, var(--bh-floor) 20%, transparent); color: color-mix(in srgb, var(--bh-floor) 75%, var(--primary-text-color)); }
.status.warn { background: color-mix(in srgb, var(--bh-warn) 22%, transparent); color: color-mix(in srgb, var(--bh-warn) 70%, var(--primary-text-color)); }

.hero { display: flex; align-items: flex-end; justify-content: space-between; margin: 10px 0 14px; }
.temp { display: flex; align-items: baseline; gap: 10px; }
.big { font-size: 3.2rem; line-height: 1; font-weight: 300; font-variant-numeric: tabular-nums; letter-spacing: -.02em; }
.big sup { font-size: 1.4rem; vertical-align: top; position: relative; top: .35rem; margin-left: 1px; }
.target { color: var(--bh-muted); font-size: .9rem; }
.hum { display: grid; grid-template-columns: auto auto; align-items: center; column-gap: 4px; justify-items: end; }
.hum ha-icon { --mdc-icon-size: 22px; color: var(--bh-water); }
.hum .hv { font-size: 1.5rem; font-variant-numeric: tabular-nums; }
.hum.mid .hv { color: color-mix(in srgb, var(--bh-warn) 80%, var(--primary-text-color)); }
.hum.hi .hv, .hum.hi ha-icon { color: var(--bh-bad); }
.mold { grid-column: 1 / -1; font-size: .75rem; color: var(--bh-muted); }
.mold.mid { color: color-mix(in srgb, var(--bh-warn) 80%, var(--primary-text-color)); }
.mold.hi { color: var(--bh-bad); }

.timeline { margin: 4px 0 2px; }
.tl-track { position: relative; height: 22px; border-radius: 11px; background: var(--bh-soft); overflow: hidden; }
.seg { position: absolute; top: 0; bottom: 0; }
.seg.pre { background: linear-gradient(90deg, transparent, var(--bh-pre)); }
.seg.towel { background: repeating-linear-gradient(135deg, color-mix(in srgb, var(--bh-towel) 55%, transparent) 0 4px, transparent 4px 8px); }
.seg.bath { background: var(--bh-water); border-radius: 3px; }
.now { position: absolute; top: -2px; bottom: -2px; width: 2px; margin-left: -1px; background: var(--primary-text-color); }
.tl-labels { position: relative; height: 16px; font-size: .7rem; color: var(--bh-water); }
.tl-label { position: absolute; transform: translateX(-50%); top: 2px; font-variant-numeric: tabular-nums; }
.tl-hours { display: flex; justify-content: space-between; font-size: .65rem; color: var(--bh-muted); opacity: .7; }
.next { margin: 6px 0 12px; font-size: .9rem; color: var(--bh-muted); }

.banner { display: flex; gap: 10px; align-items: center; padding: 10px 12px; border-radius: 12px; margin-bottom: 12px; font-size: .9rem; }
.banner.warn { background: color-mix(in srgb, var(--bh-warn) 18%, transparent); }
.banner.info { background: var(--bh-soft); color: var(--bh-muted); }

.devices { display: grid; grid-template-columns: 1fr 1fr; gap: 10px; }
.dev { text-align: left; display: grid; grid-template-columns: auto 1fr; grid-template-areas: "i n" "i s" "sub sub" "c c";
  column-gap: 10px; align-items: center; padding: 12px; border-radius: 14px; border: 1px solid var(--bh-line); min-height: 104px; }
.dev ha-icon { grid-area: i; --mdc-icon-size: 26px; color: var(--bh-muted); }
.dn { grid-area: n; font-size: .8rem; color: var(--bh-muted); }
.ds { grid-area: s; font-size: 1.05rem; font-weight: 500; }
.dsub { grid-area: sub; font-size: .78rem; color: var(--bh-muted); margin-top: 6px; line-height: 1.3; }
.chips { grid-area: c; display: flex; flex-wrap: wrap; gap: 4px; margin-top: 6px; }
.chip { font-size: .7rem; padding: 2px 7px; border-radius: 999px; background: var(--bh-soft); font-variant-numeric: tabular-nums; }
.dev.floor.active { border-color: color-mix(in srgb, var(--bh-floor) 60%, transparent); background: color-mix(in srgb, var(--bh-floor) 9%, transparent); }
.dev.floor.active ha-icon { color: var(--bh-floor); }
.dev.towel.active { border-color: color-mix(in srgb, var(--bh-towel) 55%, transparent); background: color-mix(in srgb, var(--bh-towel) 8%, transparent); }
.dev.towel.active ha-icon { color: var(--bh-towel); }

.actions { display: grid; grid-template-columns: 1fr 1fr; gap: 10px; margin: 12px 0; }
.actions button { white-space: nowrap; padding: 0 10px; display: flex; align-items: center; justify-content: center; gap: 8px; min-height: 48px; border-radius: 14px; font-weight: 500; }
.primary { background: var(--bh-water); color: #fff; }
.primary.stop { background: color-mix(in srgb, var(--bh-water) 20%, transparent); color: var(--bh-water); }
.secondary { border: 1px solid var(--bh-line); }
.secondary.on { border-color: var(--bh-towel); color: var(--bh-towel); }
.pressed { opacity: .6; }

.modes { display: flex; gap: 4px; padding: 4px; border-radius: 14px; background: var(--bh-soft); }
.mode { flex: 1; display: flex; flex-direction: column; align-items: center; gap: 2px; padding: 6px 2px; border-radius: 10px; font-size: .72rem; color: var(--bh-muted); }
.mode ha-icon { --mdc-icon-size: 20px; }
.mode.on { background: var(--card-background-color, var(--ha-card-background, #fff)); color: var(--primary-text-color); box-shadow: 0 1px 2px rgba(0,0,0,.12); }

.energy { margin-top: 16px; padding-top: 12px; border-top: 1px solid var(--bh-line); }
.en-head { display: flex; justify-content: space-between; align-items: center; gap: 8px; flex-wrap: wrap; }
h3 { margin: 0; font-size: .85rem; font-weight: 500; color: var(--bh-muted); }
.tabs { display: flex; gap: 2px; }
.tab { padding: 4px 9px; border-radius: 8px; font-size: .78rem; color: var(--bh-muted); }
.tab.on { background: color-mix(in srgb, var(--bh-towel) 15%, transparent); color: var(--primary-text-color); }
.en-vals { display: grid; grid-template-columns: 1fr 1fr; gap: 10px; margin-top: 8px; }
.ev { font-size: 1.8rem; font-weight: 300; font-variant-numeric: tabular-nums; }
.eu { margin-left: 6px; color: var(--bh-muted); font-size: .85rem; }
.en-prev { margin: 4px 0 0; font-size: .78rem; color: var(--bh-muted); display: flex; justify-content: space-between; gap: 8px; flex-wrap: wrap; }

.settings-toggle { width: 100%; display: flex; align-items: center; gap: 8px; padding: 12px 2px 8px; margin-top: 8px;
  color: var(--bh-muted); font-size: .85rem; border-top: 1px solid var(--bh-line); }
.settings-toggle .chev { margin-left: auto; }
.settings-toggle ha-icon { --mdc-icon-size: 20px; }
.settings { padding: 4px 0 8px; }
.scheds { display: grid; grid-template-columns: 1fr; gap: 12px; }
.sched .slot input[type=time] { max-width: 140px; }
h4 { margin: 0 0 6px; font-size: .8rem; font-weight: 500; }
.slot { display: flex; align-items: center; gap: 4px; margin-bottom: 6px; }
input { font: inherit; color: var(--primary-text-color); background: var(--bh-soft); border: 1px solid var(--bh-line); border-radius: 8px; padding: 6px; min-width: 0; }
input[type=time] { width: 100%; font-variant-numeric: tabular-nums; }
.icon { display: inline-flex; align-items: center; justify-content: center; width: 32px; height: 32px; border-radius: 8px; flex: none; }
.icon ha-icon { --mdc-icon-size: 18px; }
.add { display: inline-flex; align-items: center; gap: 4px; font-size: .8rem; color: var(--primary-color); padding: 4px 0; }
.add ha-icon { --mdc-icon-size: 18px; }
.nums { margin-top: 12px; display: grid; gap: 6px; }
.num { display: flex; align-items: center; justify-content: space-between; gap: 8px; font-size: .85rem; }
.nwrap { display: flex; align-items: center; gap: 2px; }
.nwrap input { width: 64px; text-align: center; -moz-appearance: textfield; }
.nwrap input::-webkit-inner-spin-button { -webkit-appearance: none; }
.nwrap em { font-style: normal; color: var(--bh-muted); font-size: .75rem; min-width: 42px; }
.learn { font-size: .75rem; color: var(--bh-muted); margin: 12px 0 0; }

@media (max-width: 420px) {
  .big { font-size: 2.7rem; }
  .mode span { font-size: .66rem; }
}
@media (prefers-reduced-motion: no-preference) {
  .dev, .mode, .tab, .actions button { transition: background-color .2s, border-color .2s, color .2s; }
}
`;

class BathroomHeatingCardEditor extends HTMLElement {
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
      this._form.schema = [
        { name: "entity", required: true, selector: { entity: { filter: { integration: "bathroom_heating", domain: "sensor" } } } },
        { name: "title", selector: { text: {} } },
      ];
      this._form.computeLabel = (s) => (s.name === "entity" ? "Állapot szenzor" : "Cím");
      this._form.addEventListener("value-changed", (ev) => {
        const e = new Event("config-changed", { bubbles: true, composed: true });
        e.detail = { config: ev.detail.value };
        this.dispatchEvent(e);
      });
      this.appendChild(this._form);
    }
    this._form.hass = this._hass;
    this._form.data = this._config;
  }
}

if (!customElements.get("bathroom-heating-card")) {
  customElements.define("bathroom-heating-card", BathroomHeatingCard);
  customElements.define("bathroom-heating-card-editor", BathroomHeatingCardEditor);
  window.customCards = window.customCards || [];
  window.customCards.push({
    type: "bathroom-heating-card",
    name: "Fürdőszoba fűtés",
    description: "Padlófűtés + törölközőszárító vezérlés, páratartalom és fogyasztás",
    preview: true,
  });
  console.info(`%c BATHROOM-HEATING-CARD %c ${CARD_VERSION} `, "background:#3a9fd8;color:#fff", "");
}
