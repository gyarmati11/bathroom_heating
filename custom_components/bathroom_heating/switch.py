"""Feature switches."""

from __future__ import annotations

from typing import Any

from homeassistant.components.switch import SwitchEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import EntityCategory
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.restore_state import RestoreEntity

from .const import DOMAIN
from .entity import BathroomEntity


async def async_setup_entry(
    hass: HomeAssistant, entry: ConfigEntry, async_add_entities: AddEntitiesCallback
) -> None:
    coord = hass.data[DOMAIN][entry.entry_id]
    async_add_entities(
        [
            SettingSwitch(coord, "mold_protect", "Penészvédelmi szárítás", "mdi:shield-sun"),
            SettingSwitch(coord, "notify", "Szellőztetési értesítés", "mdi:bell-ring"),
        ]
    )


class SettingSwitch(BathroomEntity, SwitchEntity, RestoreEntity):
    _attr_entity_category = EntityCategory.CONFIG

    async def async_added_to_hass(self) -> None:
        await super().async_added_to_hass()
        last = await self.async_get_last_state()
        if last is not None and last.state in ("on", "off"):
            self.coordinator.settings[self.key] = last.state == "on"

    @property
    def is_on(self) -> bool:
        return bool(self.coordinator.settings[self.key])

    async def async_turn_on(self, **kwargs: Any) -> None:
        await self.coordinator.async_set_setting(self.key, True)
        self.async_write_ha_state()

    async def async_turn_off(self, **kwargs: Any) -> None:
        await self.coordinator.async_set_setting(self.key, False)
        self.async_write_ha_state()
