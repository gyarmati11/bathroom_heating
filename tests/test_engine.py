"""Scenario tests for the pure decision engine (no Home Assistant needed)."""

import importlib.util
import sys
import pathlib
from datetime import datetime, timedelta, timezone

_p = pathlib.Path(__file__).parents[1] / "custom_components/bathroom_heating/engine.py"
_spec = importlib.util.spec_from_file_location("engine", _p)
E = importlib.util.module_from_spec(_spec)
sys.modules["engine"] = E
_spec.loader.exec_module(E)

TZ = timezone(timedelta(hours=1))
S = dict(E.DEFAULT_SETTINGS)


def at(h, m=0, day=26):  # 2026-10-26 is a Monday
    return datetime(2026, 10, day, h, m, tzinfo=TZ)


def inp(now, **kw):
    base = dict(room_temp=21.0, humidity=55.0, return_temp=22.0, battery=50.0)
    base.update(kw)
    return E.Inputs(now=now, **base)


def test_parse_schedule():
    assert len(E.parse_schedule("06:30-07:00; 20:00-21:00")) == 2
    assert E.parse_schedule("bad;  23:30-00:30")[0][1].hour == 0
    assert E.parse_schedule("") == []


def test_preheat_and_boiler_cycle():
    e = E.Engine()
    d = e.step(inp(at(16, 30), room_temp=20.5), S)
    assert not d.preheat_active and d.floor_target == 20.0
    d = e.step(inp(at(17, 5), room_temp=20.5), S)  # 180 min cap -> 17:00
    assert d.preheat_active and d.floor_target == 24.0
    assert d.floor_demand and d.pump_on and d.boiler_request
    # return water warm enough -> boiler stops, pump keeps circulating
    d = e.step(inp(at(17, 30), room_temp=21.5, return_temp=30.5), S)
    assert d.pump_on and not d.boiler_request
    d = e.step(inp(at(17, 40), room_temp=21.7, return_temp=28.0), S)
    assert not d.boiler_request  # within hysteresis
    d = e.step(inp(at(17, 50), room_temp=21.8, return_temp=26.5), S)
    assert d.boiler_request
    # room warmed up: still pre-heating (latched) until target reached
    d = e.step(inp(at(19, 0), room_temp=23.9, return_temp=26.0), S)
    assert d.preheat_active and d.floor_demand
    d = e.step(inp(at(19, 30), room_temp=24.1, return_temp=26.0), S)
    assert not d.floor_demand and not d.pump_on and not d.boiler_request
    d = e.step(inp(at(20, 10), room_temp=24.0), S)
    assert d.bath_active and d.status.startswith("Fürdés")


def test_house_heating_never_touched():
    e = E.Engine()
    d = e.step(inp(at(19, 0), room_temp=21, house_heating=True), S)
    assert d.floor_demand and d.pump_on and not d.boiler_request
    assert "Ház" in d.floor_reason


def test_towel_before_during_after_bath():
    e = E.Engine()
    assert e.step(inp(at(19, 45), room_temp=23.5), S).towel_on  # 20 min before
    assert e.step(inp(at(20, 30), room_temp=24), S).towel_on
    d = e.step(inp(at(21, 20), room_temp=24), S)
    assert d.towel_on and "után" in d.towel_reason
    d = e.step(inp(at(21, 31), room_temp=24, humidity=60), S)
    assert d.towel_on is False
    # humid after bath -> keep drying up to extra 60 min
    e2 = E.Engine()
    d = e2.step(inp(at(21, 45), room_temp=24, humidity=70), S)
    assert d.towel_on and "Szárítás" in d.towel_reason
    d = e2.step(inp(at(22, 35), room_temp=24, humidity=70), S)
    assert d.towel_on is False  # extra drying window over, rh < mold limit
    e3 = E.Engine()  # persistent high humidity (no steam spike) -> mold protection
    d = e3.step(inp(at(22, 40), room_temp=24, humidity=78), S)
    assert d.towel_on and "Penész" in d.towel_reason



def test_battery_hysteresis_and_cold():
    e = E.Engine()
    assert e.step(inp(at(13), room_temp=22, battery=91), S).towel_on
    assert e.step(inp(at(13, 5), room_temp=22, battery=87), S).towel_on
    assert e.step(inp(at(13, 10), room_temp=22, battery=84), S).towel_on is False
    d = e.step(inp(at(13, 15), room_temp=20.8, battery=50), S)
    assert d.towel_on and "Hideg" in d.towel_reason
    d = e.step(inp(at(13, 20), room_temp=21.2, battery=50), S)
    assert d.towel_on  # hysteresis
    d = e.step(inp(at(23, 0), room_temp=20.0, battery=50), S)
    assert d.towel_on is False  # night


def test_ventilation_notification_once():
    e = E.Engine()
    n = []
    for i in range(0, 25):
        d = e.step(inp(at(10, 0) + timedelta(minutes=i), humidity=72, room_temp=22), S)
        n += d.notifications
    assert d.ventilation_needed and len(n) == 1 and d.mold_risk in ("közepes", "magas")
    d = e.step(inp(at(10, 30), humidity=72, window_open=True, room_temp=22), S)
    assert not d.ventilation_needed and d.pump_on is False and d.towel_on is False
    d = e.step(inp(at(10, 40), humidity=55, window_open=True, room_temp=21), S)
    assert any(x["key"] == "close" for x in d.notifications)


def test_ventilation_not_helpful_when_outside_humid():
    e = E.Engine()
    for i in range(15):
        d = e.step(inp(at(10, i), humidity=70, room_temp=20, outdoor_temp=19, outdoor_humidity=95), S)
    assert not d.ventilation_needed and "nem segít" in d.ventilation_hint


def test_shower_detection_runs_towel():
    e = E.Engine()
    e.step(inp(at(15, 0), humidity=55, room_temp=22), S)
    d = e.step(inp(at(15, 6), humidity=78, room_temp=22.5), S)
    assert d.towel_on and "után" in d.towel_reason


def test_manual_bath_and_off_mode():
    e = E.Engine()
    e.start_bath(at(14), 45)
    d = e.step(inp(at(14, 1), room_temp=22), S)
    assert d.bath_active and d.floor_target == 24 and d.towel_on
    e.stop_bath(at(14, 20))
    d = e.step(inp(at(14, 21), room_temp=22), S)
    assert not d.bath_active and "után" in d.towel_reason
    s = dict(S, mode="off")
    d = e.step(inp(at(14, 22)), s)
    assert d.pump_on is False and d.towel_on is False and not d.boiler_request
    d = e.step(inp(at(14, 23)), s)
    assert d.pump_on is None and d.towel_on is None  # hands off afterwards


def test_rate_learning():
    e = E.Engine()
    s = dict(S, mode="comfort")
    e.step(inp(at(9, 0), room_temp=21.0), s)
    e.step(inp(at(10, 0), room_temp=23.0), s)
    e.step(inp(at(10, 30), room_temp=24.1), s)  # target reached -> episode ends
    assert e.rate > E.DEFAULT_RATE


def test_energy_power_and_rollover():
    t = E.EnergyTracker()
    now = at(22, 0)
    for i in range(121):  # 60 min at 30 s, 400 W
        t.from_power(now + timedelta(seconds=30 * i), 400, 70)
    s = t.summary()
    assert abs(s["day"]["kwh"] - 0.4) < 0.01 and s["day"]["ft"] == 28
    t.from_power(now + timedelta(hours=2, seconds=30), 0, 70)
    t.from_power(now + timedelta(hours=2, seconds=60), 0, 70)
    s = t.summary()
    assert s["day"]["prev_kwh"] > 0.39 and s["month"]["kwh"] > 0.39


def test_energy_meter_reset():
    t = E.EnergyTracker()
    t.from_energy_meter(at(10), 100.0, 70)
    t.from_energy_meter(at(11), 100.5, 70)
    t.from_energy_meter(at(12), 0.1, 70)  # plug reset
    t.from_energy_meter(at(13), 0.3, 70)
    assert abs(t.summary()["day"]["kwh"] - 0.7) < 1e-6
    t2 = E.EnergyTracker()
    t2.from_dict(t.to_dict())
    assert t2.summary() == t.summary()


def test_persist_engine():
    e = E.Engine()
    e.start_bath(at(14), 30)
    e.rate = 1.7
    e2 = E.Engine()
    e2.from_dict(e.to_dict())
    assert e2.rate == 1.7 and e2.manual_bath == e.manual_bath
