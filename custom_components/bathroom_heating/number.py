"""Adjustable settings (temperatures, thresholds, durations, price)."""

from __future__ import annotations

from dataclasses import dataclass

from homeassistant.components.number import NumberEntity, NumberMode
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import PERCENTAGE, EntityCategory, UnitOfTemperature, UnitOfTime
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.restore_state import RestoreEntity

from .const import DOMAIN
from .entity import BathroomEntity


@dataclass(frozen=True)
class NumDef:
    key: str
    name: str
    min: float
    max: float
    step: float
    unit: str | None
    icon: str
    config: bool = True  # shown under "Configuration" on the device page


NUMBERS = [
    NumDef("comfort_temp", "Fürdési hőmérséklet", 18, 28, 0.5, UnitOfTemperature.CELSIUS, "mdi:shower-head", False),
    NumDef("eco_temp", "Takarékos hőmérséklet", 15, 24, 0.5, UnitOfTemperature.CELSIUS, "mdi:leaf", False),
    NumDef("away_temp", "Távol hőmérséklet", 8, 20, 0.5, UnitOfTemperature.CELSIUS, "mdi:home-export-outline"),
    NumDef("towel_min_temp", "Törölköző: napközbeni minimum", 15, 26, 0.5, UnitOfTemperature.CELSIUS, "mdi:thermometer-low"),
    NumDef("battery_on", "Törölköző: akku küszöb", 10, 100, 1, PERCENTAGE, "mdi:home-battery"),
    NumDef("towel_before", "Törölköző: fürdés előtt", 0, 120, 5, UnitOfTime.MINUTES, "mdi:timer-sand"),
    NumDef("towel_after", "Törölköző: fürdés után", 0, 180, 5, UnitOfTime.MINUTES, "mdi:timer-sand-complete"),
    NumDef("towel_dry_extra", "Törölköző: max. extra szárítás", 0, 180, 5, UnitOfTime.MINUTES, "mdi:tumble-dryer"),
    NumDef("humidity_limit", "Páratartalom határ", 50, 85, 1, PERCENTAGE, "mdi:water-percent-alert"),
    NumDef("return_limit", "Visszatérő víz cél", 22, 45, 0.5, UnitOfTemperature.CELSIUS, "mdi:coolant-temperature"),
    NumDef("flow_setpoint", "Előremenő víz kérés", 30, 70, 1, UnitOfTemperature.CELSIUS, "mdi:fire"),
    NumDef("preheat_max", "Max. előfűtési idő", 30, 360, 10, UnitOfTime.MINUTES, "mdi:clock-start"),
    NumDef("bath_duration", "Fürdés most: időtartam", 10, 180, 5, UnitOfTime.MINUTES, "mdi:bathtub"),
    NumDef("price", "Áramár", 0, 500, 0.1, "Ft/kWh", "mdi:cash", False),
]


async def async_setup_entry(
    hass: HomeAssistant, entry: ConfigEntry, async_add_entities: AddEntitiesCallback
) -> None:
    coord = hass.data[DOMAIN][entry.entry_id]
    async_add_entities(SettingNumber(coord, d) for d in NUMBERS)


class SettingNumber(BathroomEntity, NumberEntity, RestoreEntity):
    _attr_mode = NumberMode.BOX

    def __init__(self, coordinator, d: NumDef) -> None:
        super().__init__(coordinator, d.key, d.name, d.icon)
        self._attr_native_min_value = d.min
        self._attr_native_max_value = d.max
        self._attr_native_step = d.step
        self._attr_native_unit_of_measurement = d.unit
        if d.config:
            self._attr_entity_category = EntityCategory.CONFIG

    async def async_added_to_hass(self) -> None:
        await super().async_added_to_hass()
        last = await self.async_get_last_state()
        if last is not None:
            try:
                self.coordinator.settings[self.key] = float(last.state)
            except ValueError:
                pass

    @property
    def native_value(self) -> float:
        return float(self.coordinator.settings[self.key])

    async def async_set_native_value(self, value: float) -> None:
        await self.coordinator.async_set_setting(self.key, float(value))
        self.async_write_ha_state()
