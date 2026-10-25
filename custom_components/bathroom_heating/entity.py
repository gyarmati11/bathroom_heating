"""Base entity."""

from __future__ import annotations

from homeassistant.core import callback
from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.entity import Entity

from .const import CONF_NAME, DOMAIN, MANUFACTURER, VERSION
from .coordinator import BathroomCoordinator


class BathroomEntity(Entity):
    """Common base: device grouping, coordinator updates, entity-id registry."""

    _attr_has_entity_name = True
    _attr_should_poll = False

    def __init__(self, coordinator: BathroomCoordinator, key: str, name: str, icon: str | None = None) -> None:
        self.coordinator = coordinator
        self.key = key
        entry = coordinator.entry
        self._attr_unique_id = f"{entry.entry_id}_{key}"
        self._attr_name = name
        if icon:
            self._attr_icon = icon
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, entry.entry_id)},
            name=coordinator.cfg.get(CONF_NAME) or entry.title or "Fürdőszoba",
            manufacturer=MANUFACTURER,
            model="Fürdőszoba fűtésvezérlő",
            sw_version=VERSION,
        )

    async def async_added_to_hass(self) -> None:
        await super().async_added_to_hass()
        self.coordinator.entity_ids[self.key] = self.entity_id
        self.async_on_remove(self.coordinator.async_add_listener(self._handle_update))

    @callback
    def _handle_update(self) -> None:
        self.async_write_ha_state()
