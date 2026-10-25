"""Smoke test of the coordinator against a tiny fake Home Assistant.

The real HA package is not required: just enough of its API is stubbed to run
the coordinator loop, drive relays and the OTGW boiler override.
"""

import asyncio
import importlib
import pathlib
import sys
import types
from datetime import datetime, timedelta, timezone

ROOT = pathlib.Path(__file__).parents[1] / "custom_components"
TZ = timezone(timedelta(hours=1))
NOW = [datetime(2026, 10, 26, 18, 0, tzinfo=TZ)]


def _mod(name, **attrs):
    m = types.ModuleType(name)
    m.__dict__.update(attrs)
    sys.modules[name] = m
    return m


class State:
    def __init__(self, eid, state, attrs=None):
        self.entity_id, self.state, self.attributes = eid, state, attrs or {}


class States(dict):
    def get(self, eid):
        return dict.get(self, eid)

    def set(self, eid, state, attrs=None):
        self[eid] = State(eid, state, attrs)


class Services:
    def __init__(self, hass):
        self.calls, self.hass = [], hass

    def has_service(self, d, s):
        return (d, s) in {("notify", "mobile_app_tel")}

    async def async_call(self, domain, service, data, blocking=False):
        self.calls.append((domain, service, data))
        if domain == "homeassistant":
            self.hass.states.set(data["entity_id"], "on" if service == "turn_on" else "off")


class Hass:
    def __init__(self):
        self.states = States()
        self.services = Services(self)
        self.data = {}


def install_stubs():
    cb = lambda f: f  # noqa: E731
    _mod("homeassistant")
    _mod("homeassistant.config_entries", ConfigEntry=object)
    _mod("homeassistant.const", STATE_ON="on", STATE_UNAVAILABLE="unavailable", STATE_UNKNOWN="unknown")
    _mod("homeassistant.core", CALLBACK_TYPE=object, Event=object, HomeAssistant=object, callback=cb)
    _mod("homeassistant.helpers")
    _mod(
        "homeassistant.helpers.event",
        async_call_later=lambda *a, **k: (lambda: None),
        async_track_state_change_event=lambda *a, **k: (lambda: None),
        async_track_time_interval=lambda *a, **k: (lambda: None),
    )
    _mod("homeassistant.helpers.start", async_at_started=lambda *a, **k: (lambda: None))

    class Store:
        def __init__(self, *a, **k):
            self.saved = None

        async def async_load(self):
            return None

        async def async_save(self, data):
            self.saved = data

        def async_delay_save(self, fn, delay):
            self.saved = fn()

    _mod("homeassistant.helpers.storage", Store=Store)
    _mod("homeassistant.util")
    _mod("homeassistant.util.dt", now=lambda: NOW[0], as_utc=lambda d: d.astimezone(timezone.utc))
    sys.modules["homeassistant.util"].dt = sys.modules["homeassistant.util.dt"]
    pkg = _mod("bathroom_heating")  # skip the package __init__ (platform imports)
    pkg.__path__ = [str(ROOT / "bathroom_heating")]


def test_coordinator_flow():
    install_stubs()
    coordmod = importlib.import_module("bathroom_heating.coordinator")
    hass = Hass()
    entry = types.SimpleNamespace(
        entry_id="e1",
        options={},
        data={
            "temp_sensor": "sensor.t",
            "humidity_sensor": "sensor.h",
            "pump_switch": "switch.pump",
            "towel_switch": "switch.towel",
            "house_heating_entity": "climate.otgw",
            "boiler_method": "otgw",
            "gateway_id": "otgw",
            "return_temp_sensor": "sensor.ret",
            "battery_sensor": "sensor.bat",
            "towel_nominal_watts": 400,
            "notify_services": ["notify.mobile_app_tel"],
        },
    )
    hass.states.set("sensor.t", "20.5")
    hass.states.set("sensor.h", "55")
    hass.states.set("sensor.ret", "22")
    hass.states.set("sensor.bat", "50")
    hass.states.set("switch.pump", "off")
    hass.states.set("switch.towel", "off")
    hass.states.set("climate.otgw", "heat", {"hvac_action": "idle", "current_temperature": 21.5, "temperature": 21.0})

    c = coordmod.BathroomCoordinator(hass, entry)

    async def run():
        await c.async_setup()
        NOW[0] = datetime(2026, 10, 26, 17, 30, tzinfo=TZ)  # inside preheat window
        await c.async_refresh()
        assert hass.states.get("switch.pump").state == "on"
        assert ("opentherm_gw", "set_control_setpoint", {"gateway_id": "otgw", "temperature": 45.0}) in hass.services.calls
        # house thermostat starts calling while we hold the override -> hand back
        hass.states.set("climate.otgw", "heat", {"hvac_action": "heating", "current_temperature": 20.0, "temperature": 21.0})
        NOW[0] += timedelta(minutes=1)
        await c.async_refresh()
        assert hass.services.calls[-1][:2] == ("opentherm_gw", "set_control_setpoint")
        assert hass.services.calls[-1][2]["temperature"] == 0
        assert hass.states.get("switch.pump").state == "on" and not c.boiler_on
        # towel before bath, energy accounted from nominal power
        NOW[0] = datetime(2026, 10, 26, 19, 45, tzinfo=TZ)
        await c.async_refresh()
        assert hass.states.get("switch.towel").state == "on"
        NOW[0] += timedelta(minutes=5)
        await c.async_refresh()
        assert c.energy.summary()["day"]["kwh"] > 0.03
        # ventilation notification goes to the phone
        hass.states.set("sensor.h", "80")
        for _ in range(12):
            NOW[0] += timedelta(minutes=1)
            await c.async_refresh()
        assert any(x[0] == "notify" and x[1] == "mobile_app_tel" for x in hass.services.calls)
        a = c.attributes()
        assert a["ventilation_needed"] and a["energy"]["day"]["ft"] >= 2
        # off mode: release everything once
        c.settings["mode"] = "off"
        NOW[0] += timedelta(minutes=1)
        await c.async_refresh()
        assert hass.states.get("switch.pump").state == "off"
        await c.async_unload()

    asyncio.run(run())
