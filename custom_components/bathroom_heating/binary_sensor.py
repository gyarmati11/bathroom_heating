"""Binary sensors for automations and the card."""

from __future__ import annotations

from homeassistant.components.binary_sensor import (
    BinarySensorDeviceClass,
    BinarySensorEntity,
)
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .const import DOMAIN
from .entity import BathroomEntity

DEFS = [
    ("ventilation_needed", "Szellőztetni kell", "mdi:window-open-variant", BinarySensorDeviceClass.PROBLEM,
     lambda c: c.decision.ventilation_needed),
    ("floor_demand", "Padlófűtés igény", "mdi:heating-coil", BinarySensorDeviceClass.HEAT,
     lambda c: c.decision.floor_demand),
    ("boiler_request", "Kazán kérés", "mdi:fire", BinarySensorDeviceClass.HEAT,
     lambda c: c.boiler_on),
    ("bath_active", "Fürdés folyamatban", "mdi:bathtub", BinarySensorDeviceClass.OCCUPANCY,
     lambda c: c.decision.bath_active),
    ("preheat_active", "Előfűtés", "mdi:clock-fast", BinarySensorDeviceClass.RUNNING,
     lambda c: c.decision.preheat_active),
]


async def async_setup_entry(
    hass: HomeAssistant, entry: ConfigEntry, async_add_entities: AddEntitiesCallback
) -> None:
    coord = hass.data[DOMAIN][entry.entry_id]
    async_add_entities(FlagSensor(coord, *d) for d in DEFS)


class FlagSensor(BathroomEntity, BinarySensorEntity):
    def __init__(self, coordinator, key, name, icon, device_class, fn) -> None:
        super().__init__(coordinator, key, name, icon)
        self._attr_device_class = device_class
        self._fn = fn

    @property
    def is_on(self) -> bool | None:
        if self.coordinator.decision is None:
            return None
        return bool(self._fn(self.coordinator))
