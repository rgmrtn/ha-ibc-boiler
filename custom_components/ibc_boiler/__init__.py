"""The IBC Boiler integration."""

from __future__ import annotations

import asyncio
import logging
from typing import Any

from homeassistant.core import HomeAssistant

from .api import IBCApiClient
from .const import CONF_HOST, PLATFORMS
from .coordinator import IBCConfigEntry, IBCDataUpdateCoordinator, IBCRuntimeData

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

    coordinator = IBCDataUpdateCoordinator(hass, entry, client)
    # Hand the decoder the model identifiers up-front so the very first
    # log-entry decode is model-aware (combi/G3 overrides).
    coordinator.set_model_info(
        model=info.get("model") if isinstance(info.get("model"), str) else None,
        model_num=info.get("model_num") if isinstance(info.get("model_num"), int) else None,
    )
    await coordinator.async_config_entry_first_refresh()

    entry.runtime_data = IBCRuntimeData(
        client=client,
        coordinator=coordinator,
        info=info,
        network=network,
    )

    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)

    entry.async_on_unload(entry.add_update_listener(_async_update_listener))

    return True


async def async_unload_entry(hass: HomeAssistant, entry: IBCConfigEntry) -> bool:
    """Unload an IBC Boiler config entry."""
    return await hass.config_entries.async_unload_platforms(entry, PLATFORMS)


async def _async_update_listener(hass: HomeAssistant, entry: IBCConfigEntry) -> None:
    """Reload the entry when options (e.g. scan interval) change."""
    await hass.config_entries.async_reload(entry.entry_id)
