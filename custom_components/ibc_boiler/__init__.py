"""The IBC Boiler integration."""

from __future__ import annotations

import asyncio
import logging
from typing import Any

from homeassistant.core import HomeAssistant

from .api import IBCApiClient
from .const import (
    CONF_ERROR_LOG_SCAN_INTERVAL,
    CONF_HOST,
    CONF_LIFETIME_SCAN_INTERVAL,
    CONF_LIVE_SCAN_INTERVAL,
    CONF_SCAN_INTERVAL,
    CONF_SICC_SCAN_INTERVAL,
    DEFAULT_ERROR_LOG_SCAN_INTERVAL,
    DEFAULT_LIFETIME_SCAN_INTERVAL,
    DEFAULT_LIVE_SCAN_INTERVAL,
    DEFAULT_SICC_SCAN_INTERVAL,
    ENDPOINT_ERROR_LOG,
    ENDPOINT_LIFETIME,
    ENDPOINT_LIVE,
    ENDPOINT_SICC,
    PLATFORMS,
)
from .coordinator import (
    IBCConfigEntry,
    IBCEndpointCoordinator,
    IBCErrorLogCoordinator,
    IBCLifetimeCoordinator,
    IBCLiveCoordinator,
    IBCRuntimeData,
    IBCSiccCoordinator,
)

_LOGGER = logging.getLogger(__name__)


async def async_setup_entry(hass: HomeAssistant, entry: IBCConfigEntry) -> bool:
    """Set up an IBC Boiler config entry."""
    client = IBCApiClient(hass, entry.data[CONF_HOST])

    # Static device + network info — fetched once in parallel. If either
    # fails we still let setup proceed; DeviceInfo falls back to defaults
    # and the live poll will surface the real error via UpdateFailed.
    info_res, network_res = await asyncio.gather(
        client.async_get_info(),
        client.async_get_network(),
        return_exceptions=True,
    )
    info: dict[str, Any] = {}
    network: dict[str, Any] = {}
    if isinstance(info_res, dict):
        info = info_res
    elif isinstance(info_res, BaseException):
        _LOGGER.warning("IBC boiler info fetch failed: %s", info_res)
    if isinstance(network_res, dict):
        network = network_res
    elif isinstance(network_res, BaseException):
        _LOGGER.warning("IBC boiler network fetch failed: %s", network_res)

    live = IBCLiveCoordinator(hass, entry, client)
    error_log = IBCErrorLogCoordinator(hass, entry, client)
    lifetime = IBCLifetimeCoordinator(hass, entry, client)
    sicc = IBCSiccCoordinator(hass, entry, client)
    coordinators: dict[str, IBCEndpointCoordinator] = {
        ENDPOINT_LIVE: live,
        ENDPOINT_ERROR_LOG: error_log,
        ENDPOINT_LIFETIME: lifetime,
        ENDPOINT_SICC: sicc,
    }

    # bool is a subclass of int in Python; reject it explicitly so a stray
    # boolean in the JSON wouldn't get propagated as model_num.
    raw_model = info.get("model")
    raw_model_num = info.get("model_num")
    error_log.set_model_info(
        model=raw_model if isinstance(raw_model, str) else None,
        model_num=(
            raw_model_num
            if isinstance(raw_model_num, int) and not isinstance(raw_model_num, bool)
            else None
        ),
    )

    # Block setup only on the live endpoint — the slow / optional ones lazy
    # populate on their own schedule so a flaky or=6 / or=44 doesn't keep
    # the integration from coming up.
    await live.async_config_entry_first_refresh()

    entry.runtime_data = IBCRuntimeData(
        client=client,
        coordinators=coordinators,
        info=info,
        network=network,
    )

    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)

    entry.async_on_unload(entry.add_update_listener(_async_update_listener))

    return True


async def async_unload_entry(hass: HomeAssistant, entry: IBCConfigEntry) -> bool:
    """Unload an IBC Boiler config entry."""
    return await hass.config_entries.async_unload_platforms(entry, PLATFORMS)


async def async_migrate_entry(hass: HomeAssistant, entry: IBCConfigEntry) -> bool:
    """Migrate v1 (single scan_interval) entries to v2 (per-endpoint intervals)."""
    if entry.version == 1:
        old = int(
            entry.options.get(CONF_SCAN_INTERVAL, DEFAULT_LIVE_SCAN_INTERVAL)
        )
        new_options = {
            # Preserve whatever tuning the user had on the single interval.
            CONF_LIVE_SCAN_INTERVAL: old,
            # Log polling never needed to keep pace with live; clamp up.
            CONF_ERROR_LOG_SCAN_INTERVAL: max(old, DEFAULT_ERROR_LOG_SCAN_INTERVAL),
            CONF_LIFETIME_SCAN_INTERVAL: DEFAULT_LIFETIME_SCAN_INTERVAL,
            CONF_SICC_SCAN_INTERVAL: old,
        }
        hass.config_entries.async_update_entry(
            entry, options=new_options, version=2
        )
    return True


async def _async_update_listener(hass: HomeAssistant, entry: IBCConfigEntry) -> None:
    """Reload the entry when options (e.g. scan intervals) change."""
    await hass.config_entries.async_reload(entry.entry_id)
