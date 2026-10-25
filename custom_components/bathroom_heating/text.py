"""Bath schedules as editable text: '06:30-07:00; 20:00-21:00'."""

from __future__ import annotations

from homeassistant.components.text import TextEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.restore_state import RestoreEntity

from .const import DOMAIN
from .engine import parse_schedule
from .entity import BathroomEntity

PATTERN = r"^\s*$|^\s*\d{1,2}:\d{2}\s*-\s*\d{1,2}:\d{2}(\s*[;,]\s*\d{1,2}:\d{2}\s*-\s*\d{1,2}:\d{2})*\s*[;,]?\s*$"


async def async_setup_entry(
    hass: HomeAssistant, entry: ConfigEntry, async_add_entities: AddEntitiesCallback
) -> None:
    coord = hass.data[DOMAIN][entry.entry_id]
    async_add_entities(
        [
            ScheduleText(coord, "schedule_weekday", "Fürdési idők hétköznap"),
            ScheduleText(coord, "schedule_weekend", "Fürdési idők hétvégén"),
        ]
    )


class ScheduleText(BathroomEntity, TextEntity, RestoreEntity):
    _attr_pattern = PATTERN
    _attr_native_max = 120

    def __init__(self, coordinator, key: str, name: str) -> None:
        super().__init__(coordinator, key, name, "mdi:calendar-clock")

    async def async_added_to_hass(self) -> None:
        await super().async_added_to_hass()
        last = await self.async_get_last_state()
        if last is not None and last.state not in ("unknown", "unavailable"):
            self.coordinator.settings[self.key] = last.state

    @property
    def native_value(self) -> str:
        return str(self.coordinator.settings[self.key])

    async def async_set_value(self, value: str) -> None:
        if value.strip() and not parse_schedule(value):
            raise HomeAssistantError("Formátum: 06:30-07:00; 20:00-21:00")
        # normalise the text
        norm = "; ".join(f"{a:%H:%M}-{b:%H:%M}" for a, b in parse_schedule(value))
        await self.coordinator.async_set_setting(self.key, norm)
        self.async_write_ha_state()
