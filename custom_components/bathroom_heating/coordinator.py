"""Glue between Home Assistant and the pure decision engine."""

from __future__ import annotations

import logging
from collections.abc import Callable
from datetime import datetime, timedelta
from typing import Any

from homeassistant.config_entries import ConfigEntry
from homeassistant.const import STATE_ON, STATE_UNAVAILABLE, STATE_UNKNOWN
from homeassistant.core import CALLBACK_TYPE, Event, HomeAssistant, callback
from homeassistant.helpers.event import (
    async_call_later,
    async_track_state_change_event,
    async_track_time_interval,
)
from homeassistant.helpers.start import async_at_started
from homeassistant.helpers.storage import Store
from homeassistant.util import dt as dt_util

from .const import (
    BOILER_NONE,
    BOILER_NUMBER,
    BOILER_OTGW,
    BOILER_RESEND,
    BOILER_SWITCH,
    CONF_BATTERY,
    CONF_BOILER_ENTITY,
    CONF_BOILER_METHOD,
    CONF_GATEWAY_ID,
    CONF_HOUSE,
    CONF_HUMIDITY,
    CONF_NOTIFY,
    CONF_OUT_HUM,
    CONF_OUT_TEMP,
    CONF_PUMP,
    CONF_RETURN_TEMP,
    CONF_TEMP,
    CONF_TOWEL,
    CONF_TOWEL_ENERGY,
    CONF_TOWEL_POWER,
    CONF_TOWEL_WATTS,
    CONF_WINDOW,
    DOMAIN,
    MODE_LABELS,
    STORE_VERSION,
    UPDATE_INTERVAL,
)
from .engine import DEFAULT_SETTINGS, Decision, Engine, EnergyTracker, Inputs

_LOGGER = logging.getLogger(__name__)

BAD = (None, "", STATE_UNAVAILABLE, STATE_UNKNOWN)


class BathroomCoordinator:
    """Owns the engine, reads inputs, drives the relays and the boiler."""

    def __init__(self, hass: HomeAssistant, entry: ConfigEntry) -> None:
        self.hass = hass
        self.entry = entry
        self.cfg: dict[str, Any] = dict(entry.options) if entry.options else dict(entry.data)
        self.settings: dict[str, Any] = dict(DEFAULT_SETTINGS)
        self.engine = Engine()
        self.energy = EnergyTracker()
        self.decision: Decision | None = None
        self.inputs: Inputs | None = None
        self.entity_ids: dict[str, str] = {}
        self.boiler_on = False
        self._boiler_sent: datetime | None = None
        self._listeners: list[Callable[[], None]] = []
        self._unsubs: list[CALLBACK_TYPE] = []
        self._pending: CALLBACK_TYPE | None = None
        self._store: Store = Store(hass, STORE_VERSION, f"{DOMAIN}.{entry.entry_id}")
        self.ready = False

    # ------------------------------------------------------------ lifecycle
    async def async_setup(self) -> None:
        data = await self._store.async_load() or {}
        try:
            self.engine.from_dict(data.get("engine", {}))
            self.energy.from_dict(data.get("energy", {}))
        except (ValueError, TypeError, KeyError) as err:
            _LOGGER.warning("Could not restore saved state: %s", err)

        watched = [
            self.cfg.get(k)
            for k in (
                CONF_TEMP,
                CONF_HUMIDITY,
                CONF_RETURN_TEMP,
                CONF_BATTERY,
                CONF_HOUSE,
                CONF_WINDOW,
                CONF_TOWEL,
                CONF_PUMP,
            )
            if self.cfg.get(k)
        ]
        self._unsubs.append(
            async_track_state_change_event(self.hass, watched, self._on_state_change)
        )
        self._unsubs.append(
            async_track_time_interval(
                self.hass, self._on_tick, timedelta(seconds=UPDATE_INTERVAL)
            )
        )

        @callback
        def _started(_hass: HomeAssistant) -> None:
            # give restored settings entities and the source integrations a moment
            self._unsubs.append(async_call_later(self.hass, 10, self._on_tick))

        self._unsubs.append(async_at_started(self.hass, _started))

    async def async_unload(self) -> None:
        for unsub in self._unsubs:
            unsub()
        self._unsubs.clear()
        if self._pending:
            self._pending()
        if self.boiler_on:
            await self._set_boiler(False)
        await self._store.async_save(self._snapshot())

    def _snapshot(self) -> dict[str, Any]:
        return {"engine": self.engine.to_dict(), "energy": self.energy.to_dict()}

    def _save_later(self) -> None:
        self._store.async_delay_save(self._snapshot, 60)

    # ------------------------------------------------------------ listeners
    @callback
    def async_add_listener(self, cb: Callable[[], None]) -> CALLBACK_TYPE:
        self._listeners.append(cb)

        @callback
        def _remove() -> None:
            if cb in self._listeners:
                self._listeners.remove(cb)

        return _remove

    @callback
    def _notify_entities(self) -> None:
        for cb in list(self._listeners):
            cb()

    @callback
    def _on_state_change(self, event: Event) -> None:
        # debounce bursts of state changes
        if self._pending is None:
            self._pending = async_call_later(self.hass, 2, self._on_tick)

    async def _on_tick(self, _now: Any = None) -> None:
        self._pending = None
        await self.async_refresh()

    # ------------------------------------------------------------ commands
    async def async_set_setting(self, key: str, value: Any) -> None:
        self.settings[key] = value
        if self.ready:
            await self.async_refresh()

    async def async_start_bath(self, minutes: float | None = None) -> None:
        self.engine.start_bath(dt_util.now(), minutes or float(self.settings["bath_duration"]))
        self._save_later()
        await self.async_refresh()

    async def async_stop_bath(self) -> None:
        self.engine.stop_bath(dt_util.now())
        self._save_later()
        await self.async_refresh()

    async def async_towel_boost(self, minutes: float = 30) -> None:
        self.engine.towel_boost(dt_util.now(), minutes)
        self._save_later()
        await self.async_refresh()

    # ------------------------------------------------------------ reading
    def _state(self, key: str):
        eid = self.cfg.get(key)
        return self.hass.states.get(eid) if eid else None

    def _float(self, key: str) -> float | None:
        st = self._state(key)
        if st is None or st.state in BAD:
            return None
        try:
            return float(st.state)
        except ValueError:
            return None

    def _is_on(self, key: str) -> bool | None:
        st = self._state(key)
        if st is None or st.state in BAD:
            return None
        return st.state == STATE_ON

    def _house_heating(self) -> bool:
        """True when the house heating already runs the boiler."""
        st = self._state(CONF_HOUSE)
        if st is None or st.state in BAD:
            return False
        domain = st.entity_id.split(".")[0]
        if domain == "climate":
            if st.state == "off":
                return False
            action = st.attributes.get("hvac_action")
            if action is not None and not self.boiler_on:
                return action == "heating"
            # while we override the boiler, hvac_action reflects our own request,
            # so judge the thermostat's demand from its own temperatures
            cur = st.attributes.get("current_temperature")
            tgt = st.attributes.get("temperature")
            try:
                return float(cur) < float(tgt) - 0.1
            except (TypeError, ValueError):
                return action == "heating"
        if domain == "sensor":  # e.g. thermostat's own control setpoint
            try:
                return float(st.state) > 10
            except ValueError:
                return False
        return st.state in (STATE_ON, "heat", "heating")

    # ------------------------------------------------------------ main loop
    async def async_refresh(self) -> None:
        self.ready = True
        now = dt_util.now()
        inp = Inputs(
            now=now,
            room_temp=self._float(CONF_TEMP),
            humidity=self._float(CONF_HUMIDITY),
            return_temp=self._float(CONF_RETURN_TEMP),
            battery=self._float(CONF_BATTERY),
            house_heating=self._house_heating(),
            window_open=bool(self._is_on(CONF_WINDOW)),
            outdoor_temp=self._float(CONF_OUT_TEMP),
            outdoor_humidity=self._float(CONF_OUT_HUM),
        )
        try:
            dec = self.engine.step(inp, self.settings)
        except Exception:  # never let a logic bug leave the boiler running
            _LOGGER.exception("Bathroom heating engine failed")
            if self.boiler_on:
                await self._set_boiler(False)
            return
        self.decision = dec
        self.inputs = inp

        if dec.pump_on is not None:
            await self._ensure(CONF_PUMP, dec.pump_on)
        if dec.towel_on is not None:
            await self._ensure(CONF_TOWEL, dec.towel_on)

        if dec.boiler_request != self.boiler_on:
            await self._set_boiler(dec.boiler_request)
        elif (
            self.boiler_on
            and self._boiler_sent
            and (now - self._boiler_sent).total_seconds() > BOILER_RESEND
        ):
            await self._set_boiler(True)

        self._track_energy(now)
        for note in dec.notifications:
            await self._send_notification(note)

        self._save_later()
        self._notify_entities()

    # ------------------------------------------------------------ actuators
    async def _ensure(self, key: str, on: bool) -> None:
        eid = self.cfg.get(key)
        st = self.hass.states.get(eid) if eid else None
        if st is None or st.state in BAD:
            return
        if (st.state == STATE_ON) == on:
            return
        try:
            await self.hass.services.async_call(
                "homeassistant",
                "turn_on" if on else "turn_off",
                {"entity_id": eid},
                blocking=True,
            )
        except Exception as err:  # noqa: BLE001
            _LOGGER.warning("Could not switch %s: %s", eid, err)

    async def _set_boiler(self, on: bool) -> None:
        method = self.cfg.get(CONF_BOILER_METHOD, BOILER_NONE)
        flow = float(self.settings["flow_setpoint"])
        try:
            if method == BOILER_OTGW and self.cfg.get(CONF_GATEWAY_ID):
                # temperature 0 hands control back to the room thermostat
                await self.hass.services.async_call(
                    "opentherm_gw",
                    "set_control_setpoint",
                    {
                        "gateway_id": self.cfg[CONF_GATEWAY_ID],
                        "temperature": flow if on else 0,
                    },
                    blocking=True,
                )
            elif method == BOILER_NUMBER and self.cfg.get(CONF_BOILER_ENTITY):
                eid = self.cfg[CONF_BOILER_ENTITY]
                st = self.hass.states.get(eid)
                off_val = float(st.attributes.get("min", 0)) if st else 0
                await self.hass.services.async_call(
                    eid.split(".")[0],
                    "set_value",
                    {"entity_id": eid, "value": flow if on else off_val},
                    blocking=True,
                )
            elif method == BOILER_SWITCH and self.cfg.get(CONF_BOILER_ENTITY):
                await self.hass.services.async_call(
                    "homeassistant",
                    "turn_on" if on else "turn_off",
                    {"entity_id": self.cfg[CONF_BOILER_ENTITY]},
                    blocking=True,
                )
        except Exception as err:  # noqa: BLE001
            _LOGGER.warning("Boiler request (%s) failed: %s", on, err)
            if on:
                return  # retry next tick
        self.boiler_on = on
        self._boiler_sent = dt_util.now() if on else None

    # ------------------------------------------------------------ energy
    def _track_energy(self, now: datetime) -> None:
        price = float(self.settings["price"])
        energy = self._float(CONF_TOWEL_ENERGY)
        if self.cfg.get(CONF_TOWEL_ENERGY):
            if energy is not None:
                self.energy.from_energy_meter(now, energy, price)
            else:
                self.energy.roll(now)
            return
        if self.cfg.get(CONF_TOWEL_POWER):
            self.energy.from_power(now, self._float(CONF_TOWEL_POWER), price)
            return
        nominal = float(self.cfg.get(CONF_TOWEL_WATTS) or 0)
        on = self._is_on(CONF_TOWEL)
        self.energy.from_power(now, nominal if on else 0.0, price)

    def towel_power(self) -> float | None:
        if self.cfg.get(CONF_TOWEL_POWER):
            return self._float(CONF_TOWEL_POWER)
        nominal = self.cfg.get(CONF_TOWEL_WATTS)
        if nominal:
            return float(nominal) if self._is_on(CONF_TOWEL) else 0.0
        return None

    # ------------------------------------------------------------ notify
    async def _send_notification(self, note: dict[str, str]) -> None:
        services = self.cfg.get(CONF_NOTIFY) or []
        if isinstance(services, str):
            services = [s.strip() for s in services.split(",") if s.strip()]
        sent = False
        for svc in services:
            svc = svc.removeprefix("notify.")
            if not self.hass.services.has_service("notify", svc):
                _LOGGER.warning("Notify service notify.%s not found", svc)
                continue
            try:
                await self.hass.services.async_call(
                    "notify",
                    svc,
                    {
                        "title": note["title"],
                        "message": note["message"],
                        "data": {"tag": f"{DOMAIN}_{note['key']}", "group": DOMAIN},
                    },
                    blocking=False,
                )
                sent = True
            except Exception as err:  # noqa: BLE001
                _LOGGER.warning("Notification via %s failed: %s", svc, err)
        if not sent:
            await self.hass.services.async_call(
                "persistent_notification",
                "create",
                {
                    "title": note["title"],
                    "message": note["message"],
                    "notification_id": f"{DOMAIN}_{note['key']}",
                },
                blocking=False,
            )

    # ------------------------------------------------------------ for entities
    def attributes(self) -> dict[str, Any]:
        d = self.decision
        if d is None:
            return {"entities": self.entity_ids}
        inp = self.inputs

        def iso(v: datetime | None) -> str | None:
            return v.isoformat() if v else None

        bath_until = None
        mb = self.engine.manual_bath
        if mb and mb[0] <= inp.now < mb[1]:
            bath_until = mb[1]
        return {
            "mode": self.settings["mode"],
            "mode_label": MODE_LABELS.get(self.settings["mode"]),
            "room_temp": inp.room_temp,
            "humidity": inp.humidity,
            "return_temp": inp.return_temp,
            "battery": inp.battery,
            "house_heating": inp.house_heating,
            "window_open": inp.window_open,
            "floor_target": d.floor_target,
            "floor_demand": d.floor_demand,
            "floor_reason": d.floor_reason,
            "pump_on": self._is_on(CONF_PUMP),
            "boiler_request": self.boiler_on,
            "towel_on": self._is_on(CONF_TOWEL),
            "towel_reason": d.towel_reason,
            "towel_power": self.towel_power(),
            "towel_boost_until": iso(self.engine.towel_boost_until),
            "bath_active": d.bath_active,
            "manual_bath_until": iso(bath_until),
            "preheat_active": d.preheat_active,
            "preheat_start": iso(d.preheat_start),
            "next_bath_start": iso(d.next_bath_start),
            "next_bath_end": iso(d.next_bath_end),
            "ventilation_needed": d.ventilation_needed,
            "ventilation_hint": d.ventilation_hint,
            "mold_risk": d.mold_risk,
            "dew_point": d.dew_point,
            "humid_minutes_today": round(self.engine.above70_minutes),
            "heating_rate": self.engine.rate,
            "energy": self.energy.summary(),
            "price": self.settings["price"],
            "settings": {k: v for k, v in self.settings.items()},
            "has_return_sensor": bool(self.cfg.get(CONF_RETURN_TEMP)),
            "has_battery": bool(self.cfg.get(CONF_BATTERY)),
            "entities": self.entity_ids,
        }
