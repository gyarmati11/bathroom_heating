"""Mode selector."""

from __future__ import annotations

from homeassistant.components.select import SelectEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.restore_state import RestoreEntity

from .const import DOMAIN, MODE_LABELS
from .entity import BathroomEntity

LABEL_TO_MODE = {v: k for k, v in MODE_LABELS.items()}


async def async_setup_entry(
    hass: HomeAssistant, entry: ConfigEntry, async_add_entities: AddEntitiesCallback
) -> None:
    async_add_entities([ModeSelect(hass.data[DOMAIN][entry.entry_id])])


class ModeSelect(BathroomEntity, SelectEntity, RestoreEntity):
    _attr_options = list(MODE_LABELS.values())

    def __init__(self, coordinator) -> None:
        super().__init__(coordinator, "mode", "Üzemmód", "mdi:thermostat-auto")

    async def async_added_to_hass(self) -> None:
        await super().async_added_to_hass()
        last = await self.async_get_last_state()
        if last and last.state in LABEL_TO_MODE:
            self.coordinator.settings["mode"] = LABEL_TO_MODE[last.state]

    @property
    def current_option(self) -> str:
        return MODE_LABELS.get(self.coordinator.settings["mode"], MODE_LABELS["auto"])

    async def async_select_option(self, option: str) -> None:
        await self.coordinator.async_set_setting("mode", LABEL_TO_MODE.get(option, "auto"))
        self.async_write_ha_state()
