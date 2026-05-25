"""The IBC Boiler integration."""

from __future__ import annotations

import asyncio
import logging
from typing import Any

from homeassistant.core import HomeAssistant

from .api import IBCApiClient, IBCConnectionError, IBCResponseError
from .const import (
    CONF_ERROR_LOG_SCAN_INTERVAL,
    CONF_HOST,
    CONF_LIFETIME_SCAN_INTERVAL,
    CONF_LIVE_SCAN_INTERVAL,
    CONF_LOAD_RUNTIME_SCAN_INTERVAL,
    CONF_SCAN_INTERVAL,
    CONF_SICC_SCAN_INTERVAL,
    DEFAULT_ERROR_LOG_SCAN_INTERVAL,
    DEFAULT_LIFETIME_SCAN_INTERVAL,
    DEFAULT_LIVE_SCAN_INTERVAL,
    DEFAULT_LOAD_RUNTIME_SCAN_INTERVAL,
    DEFAULT_SICC_SCAN_INTERVAL,
    ENDPOINT_ERROR_LOG,
    ENDPOINT_LIFETIME,
    ENDPOINT_LIVE,
    ENDPOINT_LOAD_RUNTIME,
    ENDPOINT_SICC,
    MAX_LOADS,
    PLATFORMS,
    SUPPORTED_LOAD_CONFIG_TYPES,
    LoadType,
)
from .coordinator import (
    IBCConfigEntry,
    IBCErrorLogCoordinator,
    IBCLifetimeCoordinator,
    IBCLiveCoordinator,
    IBCLoadRuntimeCoordinator,
    IBCRuntimeData,
    IBCSiccCoordinator,
)

_LOGGER = logging.getLogger(__name__)


def _parse_enabled_loads(load_enum: dict[str, Any]) -> list[tuple[int, int]]:
    """Read `Load{N}Type` for N in 1..MAX_LOADS, return enabled loads as
    `[(load_no, load_type), ...]`.

    A load is "enabled" when its `Load{N}Type` is not 0 (Off). LoadType=6
    (Zone Of) is included even though it slaves to another load — the user
    still sees it on the boiler UI as a configured load.
    """
    enabled: list[tuple[int, int]] = []
    for load_no in range(1, MAX_LOADS + 1):
        raw = load_enum.get(f"Load{load_no}Type")
        try:
            load_type = int(raw)
        except (TypeError, ValueError):
            continue
        if load_type == LoadType.OFF:
            continue
        enabled.append((load_no, load_type))
    return enabled


async def async_setup_entry(hass: HomeAssistant, entry: IBCConfigEntry) -> bool:
    """Set up an IBC Boiler config entry."""
    client = IBCApiClient(hass, entry.data[CONF_HOST])

    # Static device + network info + per-load enumeration — fetched once in
    # parallel. If any of these fail we still let setup proceed; DeviceInfo
    # falls back to defaults and the live poll will surface the real error
    # via UpdateFailed. or=13 failing just means we end up with no per-load
    # devices for this run.
    info_res, network_res, load_enum_res = await asyncio.gather(
        client.async_get_info(),
        client.async_get_network(),
        client.async_get_load_enum(),
        return_exceptions=True,
    )
    info: dict[str, Any] = {}
    network: dict[str, Any] = {}
    load_enum: dict[str, Any] = {}
    if isinstance(info_res, dict):
        info = info_res
    elif isinstance(info_res, BaseException):
        _LOGGER.warning("IBC boiler info fetch failed: %s", info_res)
    if isinstance(network_res, dict):
        network = network_res
    elif isinstance(network_res, BaseException):
        _LOGGER.warning("IBC boiler network fetch failed: %s", network_res)
    if isinstance(load_enum_res, dict):
        load_enum = load_enum_res
    elif isinstance(load_enum_res, BaseException):
        _LOGGER.warning(
            "IBC boiler load enumeration (or=13) fetch failed: %s — no per-load "
            "devices will be created until the next reload",
            load_enum_res,
        )

    enabled_loads = _parse_enabled_loads(load_enum)
    if not enabled_loads:
        _LOGGER.info(
            "No enabled loads found via or=13 — only boiler-level entities will "
            "be created"
        )

    # Per-load config (or=16) — one fetch per enabled load with a supported
    # LoadType. Fail-quiet per load. Unsupported types skip the fetch and
    # log a request for sample submission.
    load_configs: dict[int, dict[str, Any]] = {}
    for load_no, load_type in enabled_loads:
        if load_type not in SUPPORTED_LOAD_CONFIG_TYPES:
            _LOGGER.info(
                "Load %d has LoadType=%d which doesn't yet have a confirmed "
                "or=16 schema — config sensors will be skipped. Sample "
                "submissions welcome at "
                "https://github.com/rgmrtn/ha-ibc-boiler/issues/new",
                load_no,
                load_type,
            )
            continue
        try:
            load_configs[load_no] = await client.async_get_load_config(load_no)
        except (IBCConnectionError, IBCResponseError) as err:
            _LOGGER.warning(
                "Load %d config (or=16) fetch failed: %s — per-type config "
                "sensors will be missing",
                load_no,
                err,
            )

    live = IBCLiveCoordinator(hass, entry, client)
    error_log = IBCErrorLogCoordinator(hass, entry, client)
    lifetime = IBCLifetimeCoordinator(hass, entry, client)
    sicc = IBCSiccCoordinator(hass, entry, client)
    load_runtime = IBCLoadRuntimeCoordinator(hass, entry, client, enabled_loads)

    coordinators: dict[str, Any] = {
        ENDPOINT_LIVE: live,
        ENDPOINT_ERROR_LOG: error_log,
        ENDPOINT_LIFETIME: lifetime,
        ENDPOINT_SICC: sicc,
        ENDPOINT_LOAD_RUNTIME: load_runtime,
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
        enabled_loads=enabled_loads,
        load_configs=load_configs,
    )

    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)

    entry.async_on_unload(entry.add_update_listener(_async_update_listener))

    return True


async def async_unload_entry(hass: HomeAssistant, entry: IBCConfigEntry) -> bool:
    """Unload an IBC Boiler config entry."""
    return await hass.config_entries.async_unload_platforms(entry, PLATFORMS)


async def async_migrate_entry(hass: HomeAssistant, entry: IBCConfigEntry) -> bool:
    """Migrate older entries forward.

    v1 → v2: single `scan_interval` exploded into the four per-endpoint
             intervals introduced in v0.4.
    v2 → v3: add the `load_runtime_scan_interval` option introduced in v0.5.
    """
    options = dict(entry.options or {})

    if entry.version == 1:
        old = int(options.get(CONF_SCAN_INTERVAL, DEFAULT_LIVE_SCAN_INTERVAL))
        options = {
            CONF_LIVE_SCAN_INTERVAL: old,
            CONF_ERROR_LOG_SCAN_INTERVAL: max(old, DEFAULT_ERROR_LOG_SCAN_INTERVAL),
            CONF_LIFETIME_SCAN_INTERVAL: DEFAULT_LIFETIME_SCAN_INTERVAL,
            CONF_SICC_SCAN_INTERVAL: old,
        }
        hass.config_entries.async_update_entry(entry, options=options, version=2)

    if entry.version == 2:
        options.setdefault(
            CONF_LOAD_RUNTIME_SCAN_INTERVAL, DEFAULT_LOAD_RUNTIME_SCAN_INTERVAL
        )
        hass.config_entries.async_update_entry(entry, options=options, version=3)

    return True


async def _async_update_listener(hass: HomeAssistant, entry: IBCConfigEntry) -> None:
    """Reload the entry when options (e.g. scan intervals) change."""
    await hass.config_entries.async_reload(entry.entry_id)
