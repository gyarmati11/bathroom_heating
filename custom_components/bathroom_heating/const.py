"""Constants for the Bathroom Heating integration."""

DOMAIN = "bathroom_heating"
VERSION = "1.0.0"
MANUFACTURER = "Bathroom Heating"

CARD_URL = "/bathroom_heating_card/bathroom-heating-card.js"
CARD_FILE = "bathroom-heating-card.js"

UPDATE_INTERVAL = 30  # s
BOILER_RESEND = 600  # s, re-assert the boiler override while requesting
STORE_VERSION = 1

# --- config keys
CONF_NAME = "name"
CONF_TEMP = "temp_sensor"
CONF_HUMIDITY = "humidity_sensor"
CONF_PUMP = "pump_switch"
CONF_TOWEL = "towel_switch"
CONF_HOUSE = "house_heating_entity"
CONF_BOILER_METHOD = "boiler_method"
CONF_GATEWAY_ID = "gateway_id"
CONF_BOILER_ENTITY = "boiler_entity"
CONF_RETURN_TEMP = "return_temp_sensor"
CONF_BATTERY = "battery_sensor"
CONF_TOWEL_POWER = "towel_power_sensor"
CONF_TOWEL_ENERGY = "towel_energy_sensor"
CONF_TOWEL_WATTS = "towel_nominal_watts"
CONF_WINDOW = "window_sensor"
CONF_OUT_TEMP = "outdoor_temp_sensor"
CONF_OUT_HUM = "outdoor_humidity_sensor"
CONF_NOTIFY = "notify_services"

BOILER_OTGW = "otgw"
BOILER_NUMBER = "number"
BOILER_SWITCH = "switch"
BOILER_NONE = "none"

# select option label <-> engine mode
MODE_LABELS = {
    "auto": "Automatikus",
    "comfort": "Komfort",
    "eco": "Takarékos",
    "away": "Távol",
    "off": "Ki",
}
