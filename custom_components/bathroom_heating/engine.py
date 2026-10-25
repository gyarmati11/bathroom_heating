"""Pure decision engine for the bathroom heating controller.

This module has no Home Assistant imports so the whole control logic can be
unit tested in isolation. The coordinator feeds it a snapshot of the world
(``Inputs``) plus the user's settings and applies the returned ``Decision``.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from datetime import date, datetime, time, timedelta
from typing import Any

# Modes
MODE_AUTO = "auto"
MODE_COMFORT = "comfort"
MODE_ECO = "eco"
MODE_AWAY = "away"
MODE_OFF = "off"
MODES = [MODE_AUTO, MODE_COMFORT, MODE_ECO, MODE_AWAY, MODE_OFF]

DEFAULT_SETTINGS: dict[str, Any] = {
    "mode": MODE_AUTO,
    "comfort_temp": 24.0,  # fürdéskor
    "eco_temp": 20.0,  # egyébként (penész ellen ne menjen túl alacsonyra)
    "away_temp": 17.0,  # távollét
    "towel_min_temp": 21.0,  # napközben ez alatt megy a törölközőszárító
    "day_start": "06:00",
    "day_end": "22:00",
    "battery_on": 90.0,  # akku % felett megy a törölközőszárító
    "towel_before": 20.0,  # perc fürdés előtt
    "towel_after": 30.0,  # perc fürdés után
    "towel_dry_extra": 60.0,  # max ennyivel tovább, amíg magas a pára
    "humidity_limit": 65.0,  # e felett szellőztetni kell
    "return_limit": 30.0,  # visszatérő víz: ennyi kellemes a lábnak
    "flow_setpoint": 45.0,  # előremenő víz, amit a kazántól kérünk
    "preheat_max": 180.0,  # perc
    "bath_duration": 45.0,  # "Fürdés most" hossza percben
    "price": 70.0,  # Ft/kWh
    "schedule_weekday": "06:30-07:00; 20:00-21:00",
    "schedule_weekend": "08:30-09:30; 20:00-21:00",
    "mold_protect": True,  # törölközőszárító szárít, ha tartósan magas a pára
    "notify": True,
}

TEMP_HYST = 0.3
RETURN_HYST = 3.0
BATTERY_HYST = 5.0
TOWEL_TEMP_HYST = 0.5
MOLD_RH = 75.0  # tartós pára e felett -> penészvédelmi szárítás
DEFAULT_RATE = 1.0  # °C/h a padlófűtés kezdeti becsült felfűtési sebessége
MIN_PREHEAT = 30.0
NOTIFY_COOLDOWN = timedelta(minutes=60)
VENT_DELAY = timedelta(minutes=10)


# ---------------------------------------------------------------- helpers
def parse_hhmm(value: str) -> time | None:
    try:
        hh, mm = value.strip().split(":")
        return time(int(hh) % 24, int(mm) % 60)
    except (ValueError, AttributeError):
        return None


def parse_schedule(text: str) -> list[tuple[time, time]]:
    """'06:30-07:00; 20:00-21:00' -> [(06:30, 07:00), (20:00, 21:00)]."""
    out: list[tuple[time, time]] = []
    if not text:
        return out
    for part in text.replace(",", ";").split(";"):
        if "-" not in part:
            continue
        a, b = part.split("-", 1)
        ta, tb = parse_hhmm(a), parse_hhmm(b)
        if ta is not None and tb is not None and ta != tb:
            out.append((ta, tb))
    return out


def dew_point(temp: float, rh: float) -> float:
    a, b = 17.62, 243.12
    g = math.log(max(rh, 1.0) / 100.0) + a * temp / (b + temp)
    return b * g / (a - g)


def abs_humidity(temp: float, rh: float) -> float:
    """g/m³."""
    svp = 6.112 * math.exp(17.67 * temp / (temp + 243.5))
    return svp * rh * 2.1674 / (273.15 + temp)


# ---------------------------------------------------------------- inputs
@dataclass
class Inputs:
    now: datetime
    room_temp: float | None
    humidity: float | None
    return_temp: float | None = None
    battery: float | None = None
    house_heating: bool = False
    window_open: bool = False
    outdoor_temp: float | None = None
    outdoor_humidity: float | None = None


@dataclass
class Decision:
    floor_target: float | None
    floor_demand: bool
    pump_on: bool | None  # None = ne nyúljon hozzá
    boiler_request: bool
    towel_on: bool | None  # None = ne nyúljon hozzá
    towel_reason: str
    floor_reason: str
    status: str
    bath_active: bool
    preheat_active: bool
    next_bath_start: datetime | None
    next_bath_end: datetime | None
    preheat_start: datetime | None
    ventilation_needed: bool
    ventilation_hint: str
    mold_risk: str
    dew_point: float | None
    notifications: list[dict[str, str]] = field(default_factory=list)


# ---------------------------------------------------------------- engine
class Engine:
    """Stateful controller. Call ``step`` periodically (e.g. every 30 s)."""

    def __init__(self) -> None:
        # persisted
        self.rate: float = DEFAULT_RATE
        self.manual_bath: tuple[datetime, datetime] | None = None
        self.towel_boost_until: datetime | None = None
        self.detected_bath_end: datetime | None = None
        self.above70_minutes: float = 0.0
        self.above70_day: date | None = None
        # runtime
        self.floor_demand = False
        self.boiler_request = False
        self.towel_battery = False
        self.towel_cold = False
        self.preheat_latch: datetime | None = None
        self.preheat_latch_at: datetime | None = None
        self.rh_high_since: datetime | None = None
        self.vent_needed = False
        self.window_open_since: datetime | None = None
        self.window_close_notified = False
        self.last_notified: dict[str, datetime] = {}
        self.rh_history: list[tuple[datetime, float]] = []
        self.heat_episode: tuple[datetime, float] | None = None
        self.last_step: datetime | None = None
        self.prev_mode: str | None = None

    # ---- persistence
    def to_dict(self) -> dict[str, Any]:
        def iso(d: datetime | None) -> str | None:
            return d.isoformat() if d else None

        return {
            "rate": self.rate,
            "manual_bath": [iso(self.manual_bath[0]), iso(self.manual_bath[1])]
            if self.manual_bath
            else None,
            "towel_boost_until": iso(self.towel_boost_until),
            "detected_bath_end": iso(self.detected_bath_end),
            "above70_minutes": self.above70_minutes,
            "above70_day": self.above70_day.isoformat() if self.above70_day else None,
        }

    def from_dict(self, data: dict[str, Any]) -> None:
        def p(v: str | None) -> datetime | None:
            try:
                return datetime.fromisoformat(v) if v else None
            except ValueError:
                return None

        self.rate = float(data.get("rate") or DEFAULT_RATE)
        mb = data.get("manual_bath")
        if mb and p(mb[0]) and p(mb[1]):
            self.manual_bath = (p(mb[0]), p(mb[1]))  # type: ignore[assignment]
        self.towel_boost_until = p(data.get("towel_boost_until"))
        self.detected_bath_end = p(data.get("detected_bath_end"))
        self.above70_minutes = float(data.get("above70_minutes") or 0)
        d = data.get("above70_day")
        self.above70_day = date.fromisoformat(d) if d else None

    # ---- commands
    def start_bath(self, now: datetime, minutes: float) -> None:
        self.manual_bath = (now, now + timedelta(minutes=minutes))

    def stop_bath(self, now: datetime) -> None:
        # end the running bath now -> after-bath towel drying starts
        if self.manual_bath and self.manual_bath[0] <= now < self.manual_bath[1]:
            self.manual_bath = (self.manual_bath[0], now)
        self.detected_bath_end = now

    def towel_boost(self, now: datetime, minutes: float) -> None:
        if self.towel_boost_until and self.towel_boost_until > now:
            self.towel_boost_until = None  # második nyomás = kikapcsolás
        else:
            self.towel_boost_until = now + timedelta(minutes=minutes)

    # ---- schedule
    def windows(self, now: datetime, s: dict[str, Any]) -> list[tuple[datetime, datetime]]:
        out: list[tuple[datetime, datetime]] = []
        tz = now.tzinfo
        for offset in (-1, 0, 1, 2):
            d = now.date() + timedelta(days=offset)
            key = "schedule_weekend" if d.weekday() >= 5 else "schedule_weekday"
            for a, b in parse_schedule(str(s.get(key, ""))):
                start = datetime.combine(d, a, tz)
                end = datetime.combine(d, b, tz)
                if end <= start:
                    end += timedelta(days=1)
                out.append((start, end))
        if self.manual_bath and self.manual_bath[1] > now - timedelta(days=1):
            out.append(self.manual_bath)
        out.sort()
        return out

    def preheat_minutes(self, room: float | None, target: float) -> float:
        if room is None:
            return MIN_PREHEAT
        delta = max(0.0, target - room)
        return MIN_PREHEAT if delta <= 0 else delta / max(self.rate, 0.1) * 60 + 15

    # ---- main step
    def step(self, inp: Inputs, s: dict[str, Any]) -> Decision:
        now = inp.now
        dt_min = (now - self.last_step).total_seconds() / 60 if self.last_step else 0.0
        dt_min = min(max(dt_min, 0.0), 10.0)
        self.last_step = now
        mode = s.get("mode", MODE_AUTO)
        notes: list[dict[str, str]] = []
        room, rh = inp.room_temp, inp.humidity

        # -- expire commands
        if self.towel_boost_until and self.towel_boost_until <= now:
            self.towel_boost_until = None
        if self.manual_bath and self.manual_bath[1] < now - timedelta(days=1):
            self.manual_bath = None

        # -- shower detection from humidity rise
        if rh is not None:
            self.rh_history.append((now, rh))
            cutoff = now - timedelta(minutes=15)
            self.rh_history = [x for x in self.rh_history if x[0] >= cutoff]
            low = min(v for _, v in self.rh_history)
            if rh - low >= 8 and rh >= 70:
                # still steaming -> push the detected end forward
                self.detected_bath_end = now

        # -- bath windows
        wins = self.windows(now, s)
        current = next(((a, b) for a, b in wins if a <= now < b), None)
        upcoming = next(((a, b) for a, b in wins if a > now), None)
        ended = [b for a, b in wins if b <= now]
        last_end = max(ended) if ended else None
        if self.detected_bath_end and (last_end is None or self.detected_bath_end > last_end):
            last_end = self.detected_bath_end
        bath_active = current is not None

        comfort = float(s["comfort_temp"])
        preheat_start = None
        preheat_active = False
        if upcoming and mode == MODE_AUTO:
            preheat_min = min(
                max(self.preheat_minutes(room, comfort), MIN_PREHEAT), float(s["preheat_max"])
            )
            computed = upcoming[0] - timedelta(minutes=preheat_min)
            if self.preheat_latch == upcoming[0] and self.preheat_latch_at:
                # once started, keep pre-heating even if the room warms up meanwhile
                preheat_active, preheat_start = True, self.preheat_latch_at
            elif now >= computed:
                self.preheat_latch, self.preheat_latch_at = upcoming[0], now
                preheat_active, preheat_start = True, now
            else:
                preheat_start = computed

        # -- window
        if inp.window_open:
            if self.window_open_since is None:
                self.window_open_since = now
                self.window_close_notified = False
        else:
            self.window_open_since = None

        # ================= floor heating
        floor_reason = ""
        if mode == MODE_OFF:
            target = None
        elif mode == MODE_AWAY:
            target = float(s["away_temp"])
        elif mode == MODE_COMFORT:
            target = comfort
        elif mode == MODE_ECO:
            target = float(s["eco_temp"])
        else:
            target = comfort if (bath_active or preheat_active) else float(s["eco_temp"])

        if target is None or room is None:
            self.floor_demand = False
            floor_reason = "Kikapcsolva" if target is None else "Nincs hőmérséklet adat"
        elif inp.window_open:
            self.floor_demand = False
            floor_reason = "Ablak nyitva"
        else:
            if room < target - TEMP_HYST:
                self.floor_demand = True
            elif room >= target:
                self.floor_demand = False
            floor_reason = "Fűtés" if self.floor_demand else "Elérte a célt"

        # boiler request (only when the house heating is not already running)
        ret_limit = float(s["return_limit"])
        if not self.floor_demand or inp.house_heating:
            self.boiler_request = False
        elif inp.return_temp is None:
            self.boiler_request = True
        elif self.boiler_request:
            if inp.return_temp >= ret_limit:
                self.boiler_request = False
        elif inp.return_temp < ret_limit - RETURN_HYST:
            self.boiler_request = True

        if self.floor_demand:
            if inp.house_heating:
                floor_reason = "Ház fűtése megy, csak a szivattyú"
            elif self.boiler_request:
                floor_reason = "Kazán fűt a padlóra"
            else:
                floor_reason = "Visszatérő elég meleg, kering"

        # learn heating rate (°C/h) while the floor actually gets hot water
        heating_now = self.floor_demand and (self.boiler_request or inp.house_heating)
        if heating_now and room is not None:
            if self.heat_episode is None:
                self.heat_episode = (now, room)
        elif self.heat_episode is not None and room is not None:
            t0, r0 = self.heat_episode
            hours = (now - t0).total_seconds() / 3600
            if hours >= 0.5 and room - r0 >= 0.3:
                measured = min(max((room - r0) / hours, 0.2), 4.0)
                self.rate = round(0.7 * self.rate + 0.3 * measured, 3)
            self.heat_episode = None

        pump_on: bool | None = self.floor_demand
        if mode == MODE_OFF:
            pump_on = False if self.prev_mode != MODE_OFF else None

        # ================= humidity / mold / ventilation
        dp = dew_point(room, rh) if room is not None and rh is not None else None
        if rh is not None:
            if self.above70_day != now.date():
                self.above70_day = now.date()
                self.above70_minutes = 0.0
            if rh >= 70:
                self.above70_minutes += dt_min
        if rh is None:
            mold = "ismeretlen"
        elif rh >= 80 or self.above70_minutes >= 180:
            mold = "magas"
        elif rh >= 70 or self.above70_minutes >= 60:
            mold = "közepes"
        else:
            mold = "alacsony"

        limit = float(s["humidity_limit"])
        vent_hint = ""
        helps = True
        if (
            rh is not None
            and room is not None
            and inp.outdoor_temp is not None
            and inp.outdoor_humidity is not None
        ):
            helps = abs_humidity(inp.outdoor_temp, inp.outdoor_humidity) < 0.9 * abs_humidity(
                room, rh
            )
        if rh is None:
            self.vent_needed = False
            self.rh_high_since = None
        else:
            if rh >= limit:
                self.rh_high_since = self.rh_high_since or now
            elif rh < limit - 3:
                self.rh_high_since = None
            high_long = self.rh_high_since is not None and (
                now - self.rh_high_since >= VENT_DELAY or rh >= limit + 15
            )
            if high_long and not inp.window_open and helps:
                self.vent_needed = True
            elif rh < limit - 3 or inp.window_open or not helps:
                self.vent_needed = False
        if inp.window_open:
            vent_hint = "Szellőztetés folyamatban"
        elif self.vent_needed:
            vent_hint = f"Szellőztess! Pára {rh:.0f}%"
        elif self.rh_high_since and not helps:
            vent_hint = "Kint párásabb, szellőztetés nem segít – szárítás"

        if s.get("notify", True):
            if self.vent_needed and self._may_notify("vent", now):
                notes.append(
                    {
                        "key": "vent",
                        "title": "Fürdőszoba: szellőztess!",
                        "message": f"A páratartalom {rh:.0f}% (határ {limit:.0f}%). "
                        "Nyiss ablakot 5–10 percre a penész megelőzéséhez.",
                    }
                )
            if (
                inp.window_open
                and self.window_open_since
                and now - self.window_open_since >= timedelta(minutes=5)
                and rh is not None
                and rh < limit - 5
                and not self.window_close_notified
            ):
                self.window_close_notified = True
                notes.append(
                    {
                        "key": "close",
                        "title": "Fürdőszoba: becsukhatod az ablakot",
                        "message": f"A pára {rh:.0f}%-ra csökkent, a fűtés szünetel amíg nyitva van.",
                    }
                )
        if not self.vent_needed:
            self.last_notified.pop("vent", None)

        # ================= towel radiator
        towel_on: bool | None
        towel_reason = ""
        day_s = parse_hhmm(str(s["day_start"])) or time(6, 0)
        day_e = parse_hhmm(str(s["day_end"])) or time(22, 0)
        daytime = day_s <= now.time() < day_e
        after = float(s["towel_after"])
        after_end = last_end + timedelta(minutes=after) if last_end else None
        dry_end = last_end + timedelta(minutes=after + float(s["towel_dry_extra"])) if last_end else None

        # battery with hysteresis
        if inp.battery is None:
            self.towel_battery = False
        elif inp.battery >= float(s["battery_on"]):
            self.towel_battery = True
        elif inp.battery < float(s["battery_on"]) - BATTERY_HYST:
            self.towel_battery = False
        # cold room during the day
        tmin = float(s["towel_min_temp"])
        if room is None or not daytime:
            self.towel_cold = False
        elif room < tmin:
            self.towel_cold = True
        elif room >= tmin + TOWEL_TEMP_HYST:
            self.towel_cold = False

        if mode == MODE_OFF:
            towel_on = False if self.prev_mode != MODE_OFF else None
            towel_reason = "Kikapcsolva"
        elif inp.window_open:
            towel_on, towel_reason = False, "Ablak nyitva"
        elif self.towel_boost_until:
            towel_on = True
            towel_reason = f"Kézi indítás {self.towel_boost_until:%H:%M}-ig"
        elif bath_active and mode != MODE_AWAY:
            towel_on, towel_reason = True, "Fürdés"
        elif (
            upcoming
            and mode != MODE_AWAY
            and upcoming[0] - timedelta(minutes=float(s["towel_before"])) <= now
        ):
            towel_on, towel_reason = True, f"Fürdés előtt ({upcoming[0]:%H:%M})"
        elif after_end and now < after_end and mode != MODE_AWAY:
            towel_on, towel_reason = True, f"Fürdés után {after_end:%H:%M}-ig"
        elif dry_end and now < dry_end and rh is not None and rh >= limit and mode != MODE_AWAY:
            towel_on, towel_reason = True, "Szárítás fürdés után (magas pára)"
        elif self.towel_battery:
            towel_on, towel_reason = True, f"Napelem akku {inp.battery:.0f}%"
        elif self.towel_cold and mode != MODE_AWAY:
            towel_on, towel_reason = True, f"Hideg van ({room:.1f}° < {tmin:.0f}°)"
        elif s.get("mold_protect", True) and rh is not None and rh >= MOLD_RH:
            towel_on, towel_reason = True, "Penészvédelem: szárítás"
        else:
            towel_on, towel_reason = False, "Nincs rá szükség"

        # ================= status line
        if mode == MODE_OFF:
            status = "Kikapcsolva"
        elif inp.window_open:
            status = "Ablak nyitva – fűtés szünetel"
        elif bath_active:
            status = f"Fürdés – {current[1]:%H:%M}-ig"  # type: ignore[index]
        elif preheat_active and upcoming:
            status = f"Előfűtés fürdéshez ({upcoming[0]:%H:%M})"
        elif self.vent_needed:
            status = "Szellőztetni kell"
        elif self.floor_demand:
            status = "Temperálás"
        else:
            status = {
                MODE_AWAY: "Távol – fagyvédelem",
                MODE_ECO: "Takarékos",
                MODE_COMFORT: "Komfort",
            }.get(mode, "Készenlét")

        self.prev_mode = mode
        return Decision(
            floor_target=target,
            floor_demand=self.floor_demand,
            pump_on=pump_on,
            boiler_request=self.boiler_request,
            towel_on=towel_on,
            towel_reason=towel_reason,
            floor_reason=floor_reason,
            status=status,
            bath_active=bath_active,
            preheat_active=preheat_active,
            next_bath_start=upcoming[0] if upcoming else None,
            next_bath_end=upcoming[1] if upcoming else None,
            preheat_start=preheat_start,
            ventilation_needed=self.vent_needed,
            ventilation_hint=vent_hint,
            mold_risk=mold,
            dew_point=round(dp, 1) if dp is not None else None,
            notifications=notes,
        )

    def _may_notify(self, key: str, now: datetime) -> bool:
        last = self.last_notified.get(key)
        if last is None or now - last >= NOTIFY_COOLDOWN:
            self.last_notified[key] = now
            return True
        return False


# ---------------------------------------------------------------- energy
PERIODS = ("day", "week", "month", "year")


def period_key(period: str, now: datetime) -> str:
    if period == "day":
        return now.strftime("%Y-%m-%d")
    if period == "week":
        iso = now.isocalendar()
        return f"{iso[0]}-W{iso[1]:02d}"
    if period == "month":
        return now.strftime("%Y-%m")
    return now.strftime("%Y")


class EnergyTracker:
    """Accumulates towel radiator energy (kWh) and cost (Ft) per period.

    Cost is accumulated at the price valid at the time of consumption, so a
    later price change does not rewrite history.
    """

    def __init__(self) -> None:
        self.data: dict[str, dict[str, Any]] = {
            p: {"key": None, "kwh": 0.0, "ft": 0.0, "prev_kwh": 0.0, "prev_ft": 0.0}
            for p in PERIODS
        }
        self.total_kwh = 0.0
        self.total_ft = 0.0
        self.last_energy: float | None = None
        self.last_power: float | None = None
        self.last_ts: datetime | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "data": self.data,
            "total_kwh": self.total_kwh,
            "total_ft": self.total_ft,
            "last_energy": self.last_energy,
        }

    def from_dict(self, d: dict[str, Any]) -> None:
        for p in PERIODS:
            if p in d.get("data", {}):
                self.data[p].update(d["data"][p])
        self.total_kwh = float(d.get("total_kwh") or 0)
        self.total_ft = float(d.get("total_ft") or 0)
        self.last_energy = d.get("last_energy")

    def roll(self, now: datetime) -> None:
        for p in PERIODS:
            key = period_key(p, now)
            b = self.data[p]
            if b["key"] != key:
                if b["key"] is not None:
                    b["prev_kwh"], b["prev_ft"] = b["kwh"], b["ft"]
                b["key"], b["kwh"], b["ft"] = key, 0.0, 0.0

    def add(self, now: datetime, kwh: float, price: float) -> None:
        self.roll(now)
        if kwh <= 0:
            return
        ft = kwh * price
        for p in PERIODS:
            self.data[p]["kwh"] += kwh
            self.data[p]["ft"] += ft
        self.total_kwh += kwh
        self.total_ft += ft

    # --- sources
    def from_energy_meter(self, now: datetime, value: float, price: float) -> None:
        """Cumulative kWh meter (e.g. smart plug total energy)."""
        if self.last_energy is not None:
            delta = value - self.last_energy
            if 0 < delta < 5:  # ignore resets and absurd jumps
                self.add(now, delta, price)
        self.last_energy = value
        self.roll(now)

    def from_power(self, now: datetime, watts: float | None, price: float) -> None:
        """Integrate instantaneous power (left Riemann sum, called every tick)."""
        if self.last_ts is not None and self.last_power is not None:
            hours = min((now - self.last_ts).total_seconds(), 300) / 3600
            if hours > 0:
                self.add(now, self.last_power * hours / 1000, price)
        self.last_ts, self.last_power = now, watts
        self.roll(now)

    def summary(self) -> dict[str, Any]:
        out: dict[str, Any] = {}
        for p in PERIODS:
            b = self.data[p]
            out[p] = {
                "kwh": round(b["kwh"], 3),
                "ft": round(b["ft"]),
                "prev_kwh": round(b["prev_kwh"], 3),
                "prev_ft": round(b["prev_ft"]),
            }
        out["total"] = {"kwh": round(self.total_kwh, 3), "ft": round(self.total_ft)}
        return out
