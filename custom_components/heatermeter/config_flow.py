"""Config flow for HeaterMeter integration."""
import logging

import requests
import voluptuous as vol

from homeassistant import config_entries
from homeassistant.const import CONF_API_KEY, CONF_HOST, CONF_PORT, CONF_SCAN_INTERVAL
from homeassistant.core import callback

from .const import DOMAIN

_LOGGER = logging.getLogger(__name__)

BASE_STATUS_URL = "http://{host}:{port}/luci/lm/hmstatus"


def _test_connection(host: str, port: int) -> bool:
    """Try to reach the HeaterMeter status endpoint."""
    try:
        url = BASE_STATUS_URL.format(host=host, port=port)
        response = requests.get(url, timeout=5)
        response.raise_for_status()
        response.json()
        return True
    except Exception:  # noqa: BLE001
        return False


def _build_schema(defaults: dict | None = None) -> vol.Schema:
    defaults = defaults or {}
    return vol.Schema(
        {
            vol.Required(CONF_HOST, default=defaults.get(CONF_HOST, "smoker.lan")): str,
            vol.Required(CONF_API_KEY, default=defaults.get(CONF_API_KEY, "")): str,
            vol.Optional(CONF_PORT, default=defaults.get(CONF_PORT, 80)): int,
            vol.Optional(
                CONF_SCAN_INTERVAL, default=defaults.get(CONF_SCAN_INTERVAL, 10)
            ): int,
        }
    )


class HeaterMeterConfigFlow(config_entries.ConfigFlow, domain=DOMAIN):
    """Handle a config flow for HeaterMeter."""

    VERSION = 1

    async def async_step_user(self, user_input: dict | None = None):
        """Handle the initial step shown in the UI."""
        errors: dict[str, str] = {}

        if user_input is not None:
            host = user_input[CONF_HOST]
            port = user_input[CONF_PORT]

            # Avoid duplicate entries for the same host
            await self.async_set_unique_id(f"{host}:{port}")
            self._abort_if_unique_id_configured()

            reachable = await self.hass.async_add_executor_job(
                _test_connection, host, port
            )
            if not reachable:
                errors["base"] = "cannot_connect"
            else:
                return self.async_create_entry(
                    title=f"HeaterMeter ({host})",
                    data=user_input,
                )

        return self.async_show_form(
            step_id="user",
            data_schema=_build_schema(user_input),
            errors=errors,
        )

    async def async_step_import(self, import_data: dict):
        """Handle import from YAML configuration."""
        host = import_data.get(CONF_HOST, "")
        port = import_data.get(CONF_PORT, 80)

        await self.async_set_unique_id(f"{host}:{port}")
        self._abort_if_unique_id_configured()

        return self.async_create_entry(
            title=f"HeaterMeter ({host})",
            data=import_data,
        )

    @staticmethod
    @callback
    def async_get_options_flow(config_entry):
        """Return the options flow handler."""
        return HeaterMeterOptionsFlow(config_entry)


class HeaterMeterOptionsFlow(config_entries.OptionsFlow):
    """Options flow to update scan interval and API key."""

    def __init__(self, config_entry: config_entries.ConfigEntry) -> None:
        self._entry = config_entry

    async def async_step_init(self, user_input: dict | None = None):
        """Manage options."""
        errors: dict[str, str] = {}

        if user_input is not None:
            return self.async_create_entry(title="", data=user_input)

        schema = vol.Schema(
            {
                vol.Required(
                    CONF_API_KEY,
                    default=self._entry.data.get(CONF_API_KEY, ""),
                ): str,
                vol.Optional(
                    CONF_SCAN_INTERVAL,
                    default=self._entry.data.get(CONF_SCAN_INTERVAL, 10),
                ): int,
            }
        )

        return self.async_show_form(
            step_id="init",
            data_schema=schema,
            errors=errors,
        )

