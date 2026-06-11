"""
Support for reading HeaterMeter data. See https://github.com/CapnBry/HeaterMeter/wiki/Accessing-Raw-Data-Remotely

configuration.yaml (legacy – also supported via UI):

heatermeter:
    api_key: api key from HeaterMeter API
    host: smoker.lan
    port: 80
    scan_interval: 2
"""
import logging

import requests
import homeassistant.helpers.config_validation as cv
import voluptuous as vol
from homeassistant import config_entries
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import CONF_API_KEY, CONF_HOST, CONF_PORT, CONF_SCAN_INTERVAL
from homeassistant.core import HomeAssistant, ServiceCall
from homeassistant.helpers.typing import ConfigType

from .const import ALARM_DEFAULT, ALARM_NAME, DOMAIN, SET_URL_API, TEMPERATURE_DEFAULT, TEMPERATURE_NAME

_LOGGER = logging.getLogger(__name__)

PLATFORMS = ["sensor"]

CONFIG_SCHEMA = vol.Schema(
    {
        DOMAIN: vol.Schema(
            {
                vol.Required(CONF_HOST): cv.string,
                vol.Required(CONF_API_KEY): cv.string,
                vol.Optional(CONF_PORT, default=80): cv.positive_int,
                vol.Optional(CONF_SCAN_INTERVAL, default=10): cv.positive_int,
            }
        )
    },
    extra=vol.ALLOW_EXTRA,
)


async def async_setup(hass: HomeAssistant, config: ConfigType) -> bool:
    """Import YAML configuration into a config entry."""
    hass.data.setdefault(DOMAIN, {})

    if DOMAIN in config:
        _LOGGER.debug("HeaterMeter: importing YAML config into config entry")
        hass.async_create_task(
            hass.config_entries.flow.async_init(
                DOMAIN,
                context={"source": config_entries.SOURCE_IMPORT},
                data=dict(config[DOMAIN]),
            )
        )

    return True


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Set up HeaterMeter from a config entry (UI or YAML import)."""
    hass.data.setdefault(DOMAIN, {})

    # Merge entry data with any options (options override data for api_key / scan_interval)
    conf = {**entry.data, **entry.options}

    hass.data[DOMAIN][entry.entry_id] = {
        CONF_HOST: conf[CONF_HOST],
        CONF_PORT: conf.get(CONF_PORT, 80),
        CONF_API_KEY: conf[CONF_API_KEY],
        CONF_SCAN_INTERVAL: conf.get(CONF_SCAN_INTERVAL, 10),
    }

    _LOGGER.debug("HeaterMeter async_setup_entry: data = %s", hass.data[DOMAIN][entry.entry_id])

    # ── Register services (only once for all entries) ──────────────────────

    if not hass.services.has_service(DOMAIN, "set_temperature"):

        async def handle_setpoint_api(call: ServiceCall) -> None:
            """Set the smoker temperature setpoint."""
            _LOGGER.debug("HeaterMeter handle_setpoint_api: call = %s", call)
            temp = call.data.get(TEMPERATURE_NAME, TEMPERATURE_DEFAULT)
            entry_id = _resolve_entry_id(hass, call)
            cfg = hass.data[DOMAIN].get(entry_id, {})
            if not cfg:
                _LOGGER.error("HeaterMeter: no config entry found for set_temperature")
                return
            await hass.async_add_executor_job(
                _post_config, hass, cfg, {"sp": temp}, "set_temperature"
            )

        hass.services.async_register(DOMAIN, "set_temperature", handle_setpoint_api)

    if not hass.services.has_service(DOMAIN, "set_alarms"):

        async def handle_setalarms_api(call: ServiceCall) -> None:
            """Set the smoker alarms."""
            _LOGGER.debug("HeaterMeter handle_setalarms_api: call = %s", call)
            alrm = call.data.get(ALARM_NAME, ALARM_DEFAULT)
            entry_id = _resolve_entry_id(hass, call)
            cfg = hass.data[DOMAIN].get(entry_id, {})
            if not cfg:
                _LOGGER.error("HeaterMeter: no config entry found for set_alarms")
                return
            await hass.async_add_executor_job(
                _post_config, hass, cfg, {"al": alrm}, "set_alarms"
            )

        hass.services.async_register(DOMAIN, "set_alarms", handle_setalarms_api)

    # Forward to sensor platform
    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)

    # Re-load when options change
    entry.async_on_unload(entry.add_update_listener(_async_update_listener))

    return True


async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Unload a config entry."""
    unload_ok = await hass.config_entries.async_unload_platforms(entry, PLATFORMS)

    if unload_ok:
        hass.data[DOMAIN].pop(entry.entry_id, None)

        # Remove services when no entries remain
        if not hass.data[DOMAIN]:
            hass.services.async_remove(DOMAIN, "set_temperature")
            hass.services.async_remove(DOMAIN, "set_alarms")

    return unload_ok


async def _async_update_listener(hass: HomeAssistant, entry: ConfigEntry) -> None:
    """Reload entry when options are updated."""
    await hass.config_entries.async_reload(entry.entry_id)


# ── Helpers ────────────────────────────────────────────────────────────────

def _resolve_entry_id(hass: HomeAssistant, call: ServiceCall) -> str | None:
    """Return the entry_id to use for a service call.

    Uses the first available entry (most setups only have one HeaterMeter).
    """
    for eid in hass.data.get(DOMAIN, {}):
        return eid
    return None


def _post_config(hass: HomeAssistant, cfg: dict, payload: dict, service: str) -> None:
    """POST a config change to the HeaterMeter API."""
    try:
        data = {**payload, "apikey": cfg[CONF_API_KEY]}
        url = SET_URL_API.format(cfg[CONF_HOST], cfg[CONF_PORT])
        _LOGGER.debug("HeaterMeter %s: POST %s  data=%s", service, url, data)

        r = requests.post(url, data=data, timeout=10)
        if r.status_code == 200:
            _LOGGER.info("HeaterMeter %s: success – %s", service, payload)
        elif r.status_code == 404:
            _LOGGER.warning("HeaterMeter %s: wrong API version (404)", service)
        elif r.status_code == 403:
            _LOGGER.warning("HeaterMeter %s: external API disabled (403)", service)
        else:
            _LOGGER.warning("HeaterMeter %s: unexpected HTTP %s", service, r.status_code)
    except requests.exceptions.RequestException as exc:
        _LOGGER.error("HeaterMeter %s: connection error – %s", service, exc)
