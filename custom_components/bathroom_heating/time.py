"""Daytime window for the 'cold room' towel rule."""

from __future__ import annotations

from datetime import time

from homeassistant.components.time import TimeEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import EntityCategory
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.restore_state import RestoreEntity

from .const import DOMAIN
from .engine import parse_hhmm
from .entity import BathroomEntity


async def async_setup_entry(
    hass: HomeAssistant, entry: ConfigEntry, async_add_entities: AddEntitiesCallback
) -> None:
    coord = hass.data[DOMAIN][entry.entry_id]
    async_add_entities(
        [
            SettingTime(coord, "day_start", "Nappal kezdete", "mdi:weather-sunset-up"),
            SettingTime(coord, "day_end", "Nappal vége", "mdi:weather-sunset-down"),
        ]
    )


class SettingTime(BathroomEntity, TimeEntity, RestoreEntity):
    _attr_entity_category = EntityCategory.CONFIG

    async def async_added_to_hass(self) -> None:
        await super().async_added_to_hass()
        last = await self.async_get_last_state()
        if last is not None and parse_hhmm(last.state[:5]) is not None:
            self.coordinator.settings[self.key] = last.state[:5]

    @property
    def native_value(self) -> time | None:
        return parse_hhmm(str(self.coordinator.settings[self.key]))

    async def async_set_value(self, value: time) -> None:
        await self.coordinator.async_set_setting(self.key, value.strftime("%H:%M"))
        self.async_write_ha_state()
