"""Config flow + options flow for the IBC Boiler integration."""

from __future__ import annotations

import logging
from typing import Any

import voluptuous as vol
from homeassistant.config_entries import (
    ConfigEntry,
    ConfigFlow,
    ConfigFlowResult,
    OptionsFlow,
)
from homeassistant.core import callback
from homeassistant.helpers import selector
from homeassistant.helpers.device_registry import format_mac

from .api import (
    IBCApiClient,
    IBCAuthError,
    IBCConnectionError,
    IBCResponseError,
    normalize_host,
)
from .const import (
    CONF_ERROR_LOG_SCAN_INTERVAL,
    CONF_HOST,
    CONF_LIFETIME_SCAN_INTERVAL,
    CONF_LIVE_SCAN_INTERVAL,
    CONF_SICC_SCAN_INTERVAL,
    DEFAULT_ERROR_LOG_SCAN_INTERVAL,
    DEFAULT_LIFETIME_SCAN_INTERVAL,
    DEFAULT_LIVE_SCAN_INTERVAL,
    DEFAULT_SICC_SCAN_INTERVAL,
    DOMAIN,
    MAX_SCAN_INTERVAL,
    MIN_SCAN_INTERVAL,
)

_LOGGER = logging.getLogger(__name__)


def _scan_interval_selector() -> selector.NumberSelector:
    return selector.NumberSelector(
        selector.NumberSelectorConfig(
            min=MIN_SCAN_INTERVAL,
            max=MAX_SCAN_INTERVAL,
            step=1,
            unit_of_measurement="s",
            mode=selector.NumberSelectorMode.BOX,
        )
    )


_USER_SCHEMA = vol.Schema(
    {
        vol.Required(CONF_HOST): str,
    }
)


async def _resolve_unique_id(client: IBCApiClient, host: str) -> tuple[str, str]:
    """Return (unique_id, title) for a confirmed-reachable boiler.

    Uses the MAC from object_request 34 when available; otherwise the lower-cased
    host. Title uses the boiler's configured site_name if it's set to something
    other than the factory default.
    """
    title = f"IBC Boiler ({host})"
    try:
        network = await client.async_get_network()
    except (IBCConnectionError, IBCResponseError):
        return host.lower(), title

    mac = network.get("mac")
    if isinstance(mac, str) and mac.strip():
        unique_id = format_mac(mac.strip())
    else:
        unique_id = host.lower()

    site_name = network.get("site_name")
    if isinstance(site_name, str):
        site_name = site_name.strip()
        if site_name and site_name.lower() != "ibc-boiler":
            title = site_name

    return unique_id, title


class IBCConfigFlow(ConfigFlow, domain=DOMAIN):
    """Handle a config flow for IBC Boiler."""

    VERSION = 2

    async def async_step_user(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        errors: dict[str, str] = {}

        if user_input is not None:
            host = normalize_host(str(user_input[CONF_HOST]))

            client = IBCApiClient(self.hass, host)
            try:
                await client.async_test_connection()
            except IBCConnectionError:
                errors["base"] = "cannot_connect"
            except IBCAuthError:
                errors["base"] = "invalid_auth"
            except IBCResponseError:
                errors["base"] = "invalid_response"
            except Exception:  # surface unknowns to the user, log full trace
                _LOGGER.exception("Unexpected error during IBC boiler test connection")
                errors["base"] = "unknown"
            else:
                unique_id, title = await _resolve_unique_id(client, host)
                await self.async_set_unique_id(unique_id)
                self._abort_if_unique_id_configured(updates={CONF_HOST: host})

                return self.async_create_entry(
                    title=title,
                    data={CONF_HOST: host},
                    options={
                        CONF_LIVE_SCAN_INTERVAL: DEFAULT_LIVE_SCAN_INTERVAL,
                        CONF_ERROR_LOG_SCAN_INTERVAL: DEFAULT_ERROR_LOG_SCAN_INTERVAL,
                        CONF_LIFETIME_SCAN_INTERVAL: DEFAULT_LIFETIME_SCAN_INTERVAL,
                        CONF_SICC_SCAN_INTERVAL: DEFAULT_SICC_SCAN_INTERVAL,
                    },
                )

        return self.async_show_form(
            step_id="user",
            data_schema=_USER_SCHEMA,
            errors=errors,
        )

    @staticmethod
    @callback
    def async_get_options_flow(config_entry: ConfigEntry) -> OptionsFlow:
        return IBCOptionsFlow()


class IBCOptionsFlow(OptionsFlow):
    """Edit per-endpoint scan intervals after setup."""

    async def async_step_init(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        if user_input is not None:
            return self.async_create_entry(
                title="",
                data={
                    CONF_LIVE_SCAN_INTERVAL: int(user_input[CONF_LIVE_SCAN_INTERVAL]),
                    CONF_ERROR_LOG_SCAN_INTERVAL: int(
                        user_input[CONF_ERROR_LOG_SCAN_INTERVAL]
                    ),
                    CONF_LIFETIME_SCAN_INTERVAL: int(
                        user_input[CONF_LIFETIME_SCAN_INTERVAL]
                    ),
                    CONF_SICC_SCAN_INTERVAL: int(user_input[CONF_SICC_SCAN_INTERVAL]),
                },
            )

        options = self.config_entry.options
        schema = vol.Schema(
            {
                vol.Required(
                    CONF_LIVE_SCAN_INTERVAL,
                    default=options.get(
                        CONF_LIVE_SCAN_INTERVAL, DEFAULT_LIVE_SCAN_INTERVAL
                    ),
                ): _scan_interval_selector(),
                vol.Required(
                    CONF_ERROR_LOG_SCAN_INTERVAL,
                    default=options.get(
                        CONF_ERROR_LOG_SCAN_INTERVAL, DEFAULT_ERROR_LOG_SCAN_INTERVAL
                    ),
                ): _scan_interval_selector(),
                vol.Required(
                    CONF_LIFETIME_SCAN_INTERVAL,
                    default=options.get(
                        CONF_LIFETIME_SCAN_INTERVAL, DEFAULT_LIFETIME_SCAN_INTERVAL
                    ),
                ): _scan_interval_selector(),
                vol.Required(
                    CONF_SICC_SCAN_INTERVAL,
                    default=options.get(
                        CONF_SICC_SCAN_INTERVAL, DEFAULT_SICC_SCAN_INTERVAL
                    ),
                ): _scan_interval_selector(),
            }
        )
        return self.async_show_form(step_id="init", data_schema=schema)
