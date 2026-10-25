"""Status, comfort and energy sensors."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime
from typing import Any

from homeassistant.components.sensor import (
    SensorDeviceClass,
    SensorEntity,
    SensorStateClass,
)
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import EntityCategory, UnitOfEnergy, UnitOfTemperature
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.util import dt as dt_util

from .const import DOMAIN
from .coordinator import BathroomCoordinator
from .entity import BathroomEntity

PERIOD_NAMES = {"day": "ma", "week": "e héten", "month": "e hónapban", "year": "idén"}


@dataclass(frozen=True)
class SDef:
    key: str
    name: str
    icon: str
    value: Callable[[BathroomCoordinator], Any]
    unit: str | None = None
    device_class: SensorDeviceClass | None = None
    state_class: SensorStateClass | None = None
    category: EntityCategory | None = None
    precision: int | None = None


def _dec(attr: str) -> Callable[[BathroomCoordinator], Any]:
    return lambda c: getattr(c.decision, attr) if c.decision else None


def _ts(v: datetime | None) -> datetime | None:
    return dt_util.as_utc(v) if v else None


SENSORS: list[SDef] = [
    SDef("floor_target", "Padlófűtés célhőmérséklet", "mdi:thermometer-auto", _dec("floor_target"),
         UnitOfTemperature.CELSIUS, SensorDeviceClass.TEMPERATURE, SensorStateClass.MEASUREMENT),
    SDef("dew_point", "Harmatpont", "mdi:water-thermometer", _dec("dew_point"),
         UnitOfTemperature.CELSIUS, SensorDeviceClass.TEMPERATURE, SensorStateClass.MEASUREMENT),
    SDef("mold_risk", "Penészkockázat", "mdi:bacteria-outline", _dec("mold_risk")),
    SDef("towel_reason", "Törölközőszárító oka", "mdi:radiator", _dec("towel_reason")),
    SDef("next_bath", "Következő fürdés", "mdi:calendar-clock",
         lambda c: _ts(c.decision.next_bath_start) if c.decision else None,
         device_class=SensorDeviceClass.TIMESTAMP),
    SDef("preheat_start", "Előfűtés kezdete", "mdi:clock-start",
         lambda c: _ts(c.decision.preheat_start) if c.decision else None,
         device_class=SensorDeviceClass.TIMESTAMP),
    SDef("heating_rate", "Felfűtési sebesség (tanult)", "mdi:chart-line",
         lambda c: c.engine.rate, "°C/h", category=EntityCategory.DIAGNOSTIC, precision=2),
    SDef("towel_energy_total", "Törölköző energia összesen", "mdi:lightning-bolt",
         lambda c: round(c.energy.total_kwh, 3), UnitOfEnergy.KILO_WATT_HOUR,
         SensorDeviceClass.ENERGY, SensorStateClass.TOTAL_INCREASING, precision=2),
    SDef("towel_cost_total", "Törölköző költség összesen", "mdi:cash",
         lambda c: round(c.energy.total_ft), "HUF", SensorDeviceClass.MONETARY,
         SensorStateClass.TOTAL, precision=0),
]
for _p, _label in PERIOD_NAMES.items():
    SENSORS.append(
        SDef(f"towel_energy_{_p}", f"Törölköző energia {_label}", "mdi:lightning-bolt",
             (lambda p: lambda c: round(c.energy.data[p]["kwh"], 3))(_p),
             UnitOfEnergy.KILO_WATT_HOUR, SensorDeviceClass.ENERGY,
             SensorStateClass.TOTAL_INCREASING, precision=2)
    )
    SENSORS.append(
        SDef(f"towel_cost_{_p}", f"Törölköző költség {_label}", "mdi:cash",
             (lambda p: lambda c: round(c.energy.data[p]["ft"]))(_p),
             "HUF", SensorDeviceClass.MONETARY, precision=0)
    )


async def async_setup_entry(
    hass: HomeAssistant, entry: ConfigEntry, async_add_entities: AddEntitiesCallback
) -> None:
    coord = hass.data[DOMAIN][entry.entry_id]
    async_add_entities([StatusSensor(coord), *(DefSensor(coord, d) for d in SENSORS)])


class StatusSensor(BathroomEntity, SensorEntity):
    """Main sensor: human readable status + everything the card needs."""

    def __init__(self, coordinator: BathroomCoordinator) -> None:
        super().__init__(coordinator, "status", "Állapot", "mdi:shower")

    @property
    def native_value(self) -> str:
        d = self.coordinator.decision
        return d.status if d else "Indul…"

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        attrs = self.coordinator.attributes()
        attrs["integration"] = DOMAIN
        return attrs


class DefSensor(BathroomEntity, SensorEntity):
    def __init__(self, coordinator: BathroomCoordinator, d: SDef) -> None:
        super().__init__(coordinator, d.key, d.name, d.icon)
        self._d = d
        self._attr_native_unit_of_measurement = d.unit
        self._attr_device_class = d.device_class
        self._attr_state_class = d.state_class
        self._attr_entity_category = d.category
        if d.precision is not None:
            self._attr_suggested_display_precision = d.precision

    @property
    def native_value(self) -> Any:
        return self._d.value(self.coordinator)
