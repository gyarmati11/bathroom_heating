"""Config + options flow (3 steps: basics, boiler, extras)."""

from __future__ import annotations

from typing import Any

import voluptuous as vol

from homeassistant.config_entries import ConfigEntry, ConfigFlow, ConfigFlowResult, OptionsFlow
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers import selector as sel

from .const import (
    BOILER_NONE,
    BOILER_NUMBER,
    BOILER_OTGW,
    BOILER_SWITCH,
    CONF_BATTERY,
    CONF_BOILER_ENTITY,
    CONF_BOILER_METHOD,
    CONF_GATEWAY_ID,
    CONF_HOUSE,
    CONF_HUMIDITY,
    CONF_NAME,
    CONF_NOTIFY,
    CONF_OUT_HUM,
    CONF_OUT_TEMP,
    CONF_PUMP,
    CONF_RETURN_TEMP,
    CONF_TEMP,
    CONF_TOWEL,
    CONF_TOWEL_ENERGY,
    CONF_TOWEL_POWER,
    CONF_TOWEL_WATTS,
    CONF_WINDOW,
    DOMAIN,
)

SWITCHABLE = ["switch", "light", "input_boolean"]


def _ent(domain: str | list[str], device_class: str | list[str] | None = None) -> sel.EntitySelector:
    cfg: dict[str, Any] = {"domain": domain}
    if device_class:
        cfg["device_class"] = device_class
    return sel.EntitySelector(sel.EntitySelectorConfig(**cfg))


def _opt(key: str, defaults: dict[str, Any]) -> vol.Optional:
    """Optional field pre-filled with the current value (and clearable)."""
    if defaults.get(key) not in (None, "", []):
        return vol.Optional(key, description={"suggested_value": defaults[key]})
    return vol.Optional(key)


def schema_basic(d: dict[str, Any]) -> vol.Schema:
    return vol.Schema(
        {
            vol.Required(CONF_NAME, default=d.get(CONF_NAME, "Fürdőszoba")): str,
            vol.Required(CONF_TEMP, default=d.get(CONF_TEMP, vol.UNDEFINED)): _ent("sensor", "temperature"),
            vol.Required(CONF_HUMIDITY, default=d.get(CONF_HUMIDITY, vol.UNDEFINED)): _ent("sensor", "humidity"),
            vol.Required(CONF_PUMP, default=d.get(CONF_PUMP, vol.UNDEFINED)): _ent(SWITCHABLE),
            vol.Required(CONF_TOWEL, default=d.get(CONF_TOWEL, vol.UNDEFINED)): _ent(SWITCHABLE),
        }
    )


def schema_boiler(d: dict[str, Any]) -> vol.Schema:
    return vol.Schema(
        {
            _opt(CONF_HOUSE, d): _ent(["climate", "binary_sensor", "switch", "input_boolean", "sensor"]),
            vol.Required(CONF_BOILER_METHOD, default=d.get(CONF_BOILER_METHOD, BOILER_OTGW)): sel.SelectSelector(
                sel.SelectSelectorConfig(
                    options=[
                        sel.SelectOptionDict(value=BOILER_OTGW, label="OpenTherm Gateway (OTGW) – control setpoint"),
                        sel.SelectOptionDict(value=BOILER_NUMBER, label="Szám entitás (pl. ESPHome OpenTherm előremenő)"),
                        sel.SelectOptionDict(value=BOILER_SWITCH, label="Kapcsoló (kazán fűtés engedély)"),
                        sel.SelectOptionDict(value=BOILER_NONE, label="Nincs – csak a szivattyút kapcsolja"),
                    ],
                    mode=sel.SelectSelectorMode.LIST,
                )
            ),
            _opt(CONF_GATEWAY_ID, d): sel.TextSelector(),
            _opt(CONF_BOILER_ENTITY, d): _ent(["number", "input_number", "switch", "input_boolean"]),
            _opt(CONF_RETURN_TEMP, d): _ent("sensor"),
        }
    )


def schema_extra(hass: HomeAssistant, d: dict[str, Any]) -> vol.Schema:
    notify = sorted(f"notify.{s}" for s in hass.services.async_services_for_domain("notify"))
    return vol.Schema(
        {
            _opt(CONF_BATTERY, d): _ent("sensor"),
            _opt(CONF_TOWEL_POWER, d): _ent("sensor", "power"),
            _opt(CONF_TOWEL_ENERGY, d): _ent("sensor", "energy"),
            _opt(CONF_TOWEL_WATTS, d): sel.NumberSelector(
                sel.NumberSelectorConfig(min=0, max=3000, step=10, unit_of_measurement="W", mode=sel.NumberSelectorMode.BOX)
            ),
            _opt(CONF_WINDOW, d): _ent("binary_sensor"),
            _opt(CONF_OUT_TEMP, d): _ent("sensor", "temperature"),
            _opt(CONF_OUT_HUM, d): _ent("sensor", "humidity"),
            _opt(CONF_NOTIFY, d): sel.SelectSelector(
                sel.SelectSelectorConfig(options=notify, multiple=True, custom_value=True)
            ),
        }
    )


def _validate_boiler(data: dict[str, Any]) -> dict[str, str]:
    errors: dict[str, str] = {}
    method = data.get(CONF_BOILER_METHOD)
    if method == BOILER_OTGW and not data.get(CONF_GATEWAY_ID):
        errors[CONF_GATEWAY_ID] = "gateway_required"
    if method in (BOILER_NUMBER, BOILER_SWITCH) and not data.get(CONF_BOILER_ENTITY):
        errors[CONF_BOILER_ENTITY] = "entity_required"
    return errors


class BathroomConfigFlow(ConfigFlow, domain=DOMAIN):
    VERSION = 1

    def __init__(self) -> None:
        self.data: dict[str, Any] = {}

    async def async_step_user(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        if user_input is not None:
            self.data.update(user_input)
            return await self.async_step_boiler()
        return self.async_show_form(step_id="user", data_schema=schema_basic(self.data))

    async def async_step_boiler(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        errors: dict[str, str] = {}
        if user_input is not None:
            errors = _validate_boiler(user_input)
            if not errors:
                self.data.update(user_input)
                return await self.async_step_extra()
        return self.async_show_form(
            step_id="boiler", data_schema=schema_boiler(user_input or self.data), errors=errors
        )

    async def async_step_extra(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        if user_input is not None:
            self.data.update(user_input)
            await self.async_set_unique_id(f"{DOMAIN}_{self.data[CONF_TOWEL]}")
            self._abort_if_unique_id_configured()
            return self.async_create_entry(title=self.data[CONF_NAME], data=self.data)
        return self.async_show_form(step_id="extra", data_schema=schema_extra(self.hass, self.data))

    @staticmethod
    @callback
    def async_get_options_flow(config_entry: ConfigEntry) -> OptionsFlow:
        return BathroomOptionsFlow()


class BathroomOptionsFlow(OptionsFlow):
    """Same three steps; result fully replaces the configuration."""

    def __init__(self) -> None:
        self.data: dict[str, Any] = {}

    @property
    def current(self) -> dict[str, Any]:
        e = self.config_entry
        return dict(e.options) if e.options else dict(e.data)

    async def async_step_init(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        if user_input is not None:
            self.data = dict(user_input)
            return await self.async_step_boiler()
        return self.async_show_form(step_id="init", data_schema=schema_basic(self.current))

    async def async_step_boiler(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        errors: dict[str, str] = {}
        if user_input is not None:
            errors = _validate_boiler(user_input)
            if not errors:
                self.data.update(user_input)
                return await self.async_step_extra()
        return self.async_show_form(
            step_id="boiler", data_schema=schema_boiler(user_input or self.current), errors=errors
        )

    async def async_step_extra(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        if user_input is not None:
            self.data.update(user_input)
            return self.async_create_entry(title="", data=self.data)
        return self.async_show_form(step_id="extra", data_schema=schema_extra(self.hass, self.current))
