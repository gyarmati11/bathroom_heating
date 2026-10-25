"""One-tap actions."""

from __future__ import annotations

from homeassistant.components.button import ButtonEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .const import DOMAIN
from .entity import BathroomEntity


async def async_setup_entry(
    hass: HomeAssistant, entry: ConfigEntry, async_add_entities: AddEntitiesCallback
) -> None:
    coord = hass.data[DOMAIN][entry.entry_id]
    async_add_entities(
        [
            ActionButton(coord, "bath_start", "Fürdés most", "mdi:bathtub"),
            ActionButton(coord, "bath_stop", "Fürdés vége", "mdi:bathtub-outline"),
            ActionButton(coord, "towel_boost", "Törölköző 30 perc", "mdi:radiator"),
        ]
    )


class ActionButton(BathroomEntity, ButtonEntity):
    async def async_press(self) -> None:
        if self.key == "bath_start":
            await self.coordinator.async_start_bath()
        elif self.key == "bath_stop":
            await self.coordinator.async_stop_bath()
        else:
            await self.coordinator.async_towel_boost(30)
