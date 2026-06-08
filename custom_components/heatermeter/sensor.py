"""
Support for reading HeaterMeter data. See https://github.com/CapnBry/HeaterMeter/wiki/Accessing-Raw-Data-Remotely
"""
import logging
import requests
from datetime import timedelta

import homeassistant.util.dt as dt_util
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import CONF_HOST, CONF_PORT, CONF_SCAN_INTERVAL
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity import Entity
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.util import Throttle
from homeassistant.util.unit_system import US_CUSTOMARY_SYSTEM
from homeassistant.const import UnitOfTemperature

from .const import DOMAIN

_LOGGER = logging.getLogger(__name__)

ENTITY_ID_FORMAT = DOMAIN + ".{}"
BASE_URL = "http://{0}:{1}{2}"
SCAN_INTERVAL = timedelta(seconds=2)
MIN_TIME_BETWEEN_UPDATES = timedelta(seconds=1)

SENSOR_TYPES = {
    "setpoint": ["Setpoint", "", "mdi:thermometer"],
    "lid": ["Lid", "", "mdi:room-service"],
    "fan": ["Fan", "%", "mdi:fan"],
    "alarm": ["Alarm", "", "mdi:alert"],
    "probe0_temperature": ["Pit Temperature", "", "mdi:thermometer"],
    "probe0_hi": ["Pit High", "", "mdi:thermometer"],
    "probe0_lo": ["Pit Low", "", "mdi:thermometer"],
    "probe1_temperature": ["Probe1 Temperature", "", "mdi:thermometer"],
    "probe1_hi": ["Probe1 High", "", "mdi:thermometer"],
    "probe1_lo": ["Probe1 Low", "", "mdi:thermometer"],
    "probe2_temperature": ["Probe2 Temperature", "", "mdi:thermometer"],
    "probe2_hi": ["Probe2 High", "", "mdi:thermometer"],
    "probe2_lo": ["Probe2 Low", "", "mdi:thermometer"],
    "probe3_temperature": ["Probe3 Temperature", "", "mdi:thermometer"],
    "probe3_hi": ["Probe3 High", "", "mdi:thermometer"],
    "probe3_lo": ["Probe3 Low", "", "mdi:thermometer"],
}


def _get_temp_units(hass: HomeAssistant) -> str:
    if hass.config.units is US_CUSTOMARY_SYSTEM:
        return UnitOfTemperature.FAHRENHEIT
    return UnitOfTemperature.CELSIUS


def _apply_temp_units(temp_unit: str) -> None:
    for key in (
        "setpoint",
        "probe0_temperature", "probe0_hi", "probe0_lo",
        "probe1_temperature", "probe1_hi", "probe1_lo",
        "probe2_temperature", "probe2_hi", "probe2_lo",
        "probe3_temperature", "probe3_hi", "probe3_lo",
    ):
        SENSOR_TYPES[key][1] = temp_unit


# ── Config-entry setup (UI / YAML-import) ─────────────────────────────────

async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up HeaterMeter sensors from a config entry."""
    cfg = hass.data[DOMAIN][entry.entry_id]
    host = cfg[CONF_HOST]
    port = cfg[CONF_PORT]

    _apply_temp_units(_get_temp_units(hass))

    data_obj = HeaterMeterData(host, port)

    entities = [
        HeaterMeterSensor(data_obj, sensor_type, host, entry.entry_id)
        for sensor_type in SENSOR_TYPES
    ]

    _LOGGER.debug("HeaterMeter async_setup_entry: %d entities created", len(entities))
    async_add_entities(entities, update_before_add=True)


# ── Legacy YAML setup_platform (kept for backward compat) ─────────────────

def setup_platform(hass, config, add_entities, discovery_info=None):
    """Legacy platform setup – only used when loaded directly via YAML."""
    _LOGGER.debug("HeaterMeter setup_platform: hass.data = %s", hass.data.get(DOMAIN))

    # When loaded via async_setup_entry the platform is already set up; bail out.
    if not hass.data.get(DOMAIN):
        _LOGGER.warning("HeaterMeter setup_platform called but no data found – skipping")
        return

    host = next(iter(hass.data[DOMAIN].values()))[CONF_HOST]
    port = next(iter(hass.data[DOMAIN].values()))[CONF_PORT]
    entry_id = next(iter(hass.data[DOMAIN]))

    _apply_temp_units(_get_temp_units(hass))

    try:
        data_obj = HeaterMeterData(host, port)
    except RuntimeError:
        _LOGGER.error("HeaterMeter: unable to fetch data from %s:%s", host, port)
        return False

    entities = [
        HeaterMeterSensor(data_obj, sensor_type, host, entry_id)
        for sensor_type in SENSOR_TYPES
    ]
    add_entities(entities)


# ── Data class ────────────────────────────────────────────────────────────

class HeaterMeterData:
    """Representation of a HeaterMeter data source."""

    def __init__(self, host: str, port: int) -> None:
        self._host = host
        self._port = port
        self.data = None
        self._backoff = dt_util.utcnow()

    @Throttle(MIN_TIME_BETWEEN_UPDATES)
    def update(self) -> None:
        if self._backoff > dt_util.utcnow():
            _LOGGER.debug("HeaterMeter: in backoff, skipping update")
            return

        url = BASE_URL.format(self._host, self._port, "/luci/lm/hmstatus")
        try:
            response = requests.get(url, timeout=5)
            self.data = response.json()
        except requests.exceptions.ConnectionError:
            _LOGGER.debug("HeaterMeter: no route to device %s", url)
            self.data = None
            self._backoff = dt_util.utcnow() + timedelta(seconds=60)

        _LOGGER.debug("HeaterMeter: data = %s", self.data)


# ── Sensor entity ─────────────────────────────────────────────────────────

class HeaterMeterSensor(Entity):
    """A single HeaterMeter sensor."""

    def __init__(
        self,
        data: HeaterMeterData,
        sensor_type: str,
        host: str,
        entry_id: str,
    ) -> None:
        self.data = data
        self.type = sensor_type
        self._host = host
        self._entry_id = entry_id
        self.entity_id = ENTITY_ID_FORMAT.format(sensor_type)
        self._name = SENSOR_TYPES[self.type][0]
        self._unit_of_measurement = SENSOR_TYPES[self.type][1]
        self._icon = SENSOR_TYPES[self.type][2]
        self._state = None

    # ── HA metadata ───────────────────────────────────────────────────────

    @property
    def unique_id(self) -> str:
        return f"{self._entry_id}_{self.type}"

    @property
    def device_info(self) -> DeviceInfo:
        return DeviceInfo(
            identifiers={(DOMAIN, self._host)},
            name=f"HeaterMeter ({self._host})",
            manufacturer="CapnBry",
            model="HeaterMeter BBQ Controller",
            configuration_url=f"http://{self._host}",
        )

    @property
    def name(self) -> str:
        return self._name

    @property
    def icon(self) -> str:
        return self._icon

    @property
    def state(self):
        return self._state

    @property
    def unit_of_measurement(self) -> str:
        return self._unit_of_measurement

    # ── Update ────────────────────────────────────────────────────────────

    def update(self) -> None:
        self.data.update()

        if self.data.data is None:
            self._state = "Unknown"
            return

        d = self.data.data

        if self.type == "setpoint":
            self._state = d["set"]
        elif self.type == "fan":
            self._state = d["fan"]["c"]
        elif self.type == "lid":
            self._state = "Open" if d["lid"] != 0 else "Closed"
        elif self.type == "alarm":
            self._state = (
                "on"
                if any(
                    d["temps"][i]["a"]["r"] is not None for i in range(4)
                )
                else "off"
            )
        else:
            # probe{n}_{temperature|hi|lo}
            parts = self.type.rsplit("_", 1)
            probe_key = parts[0]  # e.g. "probe0"
            measure = parts[1]    # "temperature", "hi", or "lo"
            idx = int(probe_key.replace("probe", ""))

            probe_name = d["temps"][idx]["n"]
            if measure == "temperature":
                self._state = d["temps"][idx]["c"]
                self._name = probe_name
            elif measure == "hi":
                self._state = d["temps"][idx]["a"]["h"]
                self._name = f"{probe_name} Alarm: High"
            elif measure == "lo":
                self._state = d["temps"][idx]["a"]["l"]
                self._name = f"{probe_name} Alarm: Low"
