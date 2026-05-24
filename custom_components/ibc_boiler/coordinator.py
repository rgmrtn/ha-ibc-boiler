"""Per-endpoint DataUpdateCoordinators and runtime data for IBC Boiler.

The v0.4 refactor splits the original single-coordinator polling into one
coordinator per HTTP endpoint so each can be tuned independently (live data
ticks every 30s, lifetime counters every 5 min, etc.). The live coordinator
drives device availability — it raises `UpdateFailed` on transient errors
so entities go unavailable as a group. The other coordinators fail quiet:
they catch transport errors at debug level and reuse the previous payload,
so a flaky or=6 or or=44 doesn't flicker the lifetime/flame sensors.
"""

from __future__ import annotations

import logging
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from datetime import timedelta
from typing import Any, TypeAlias

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed

from .api import IBCApiClient, IBCConnectionError, IBCResponseError
from .const import (
    CONF_ERROR_LOG_SCAN_INTERVAL,
    CONF_LIFETIME_SCAN_INTERVAL,
    CONF_LIVE_SCAN_INTERVAL,
    CONF_SICC_SCAN_INTERVAL,
    DEFAULT_ERROR_LOG_SCAN_INTERVAL,
    DEFAULT_LIFETIME_SCAN_INTERVAL,
    DEFAULT_LIVE_SCAN_INTERVAL,
    DEFAULT_SICC_SCAN_INTERVAL,
    DOMAIN,
    ENDPOINT_ERROR_LOG,
    ENDPOINT_LIFETIME,
    ENDPOINT_LIVE,
    ENDPOINT_SICC,
    EVENT_ERROR_LOGGED,
    NOT_CONNECTED_SENTINEL,
    OR_ERROR_LOG,
)
from .errors import decode_error_entry, is_empty_slot

_LOGGER = logging.getLogger(__name__)


def _temp_c(raw: Any) -> float | None:
    """or=7 stores temperatures in quarter-°C, same as the rest of the V-10."""
    try:
        v = float(raw)
    except (TypeError, ValueError):
        return None
    if v == NOT_CONNECTED_SENTINEL:
        return None
    return v / 4


def _pressure_psi(raw: Any) -> float | None:
    """or=7 reports pressures as integer tenths of psi (per error.js)."""
    try:
        v = float(raw)
    except (TypeError, ValueError):
        return None
    return v / 10


def _entry_key(entry: dict[str, Any]) -> tuple:
    """Stable identity for a log entry — changes only when a *new* event lands."""
    return (
        entry.get("log_no"),
        entry.get("Date"),
        entry.get("Time"),
        entry.get("MajErr"),
        entry.get("MinErr"),
        entry.get("SysErr"),
        entry.get("CombiErr"),
    )


FetchFn = Callable[[], Awaitable[dict[str, Any]]]


class IBCEndpointCoordinator(DataUpdateCoordinator[dict[str, Any]]):
    """Polls a single bc2-cgi endpoint on a fixed interval.

    Subclasses provide a fetch callable + failure policy. Live data raises
    `UpdateFailed` so HA marks its sensors unavailable; the slow / optional
    endpoints catch transport errors and keep the previous payload so a
    transient blip doesn't blank entities that only update on the order of
    minutes.
    """

    fail_loud: bool = False

    def __init__(
        self,
        hass: HomeAssistant,
        client: IBCApiClient,
        *,
        endpoint_id: str,
        fetch_fn: FetchFn,
        scan_interval: int,
    ) -> None:
        super().__init__(
            hass,
            _LOGGER,
            name=f"{DOMAIN} {client.host} {endpoint_id}",
            update_interval=timedelta(seconds=scan_interval),
        )
        self._client = client
        self._fetch_fn = fetch_fn
        self.endpoint_id = endpoint_id

    async def _async_update_data(self) -> dict[str, Any]:
        try:
            return await self._fetch_fn()
        except IBCConnectionError as err:
            if self.fail_loud:
                raise UpdateFailed(f"Cannot reach boiler: {err}") from err
            _LOGGER.debug(
                "%s fetch failed (connection): %s — keeping last payload",
                self.endpoint_id,
                err,
            )
            return self.data or {}
        except IBCResponseError as err:
            if self.fail_loud:
                raise UpdateFailed(f"Bad response from boiler: {err}") from err
            _LOGGER.debug(
                "%s fetch failed (response): %s — keeping last payload",
                self.endpoint_id,
                err,
            )
            return self.data or {}


class IBCLiveCoordinator(IBCEndpointCoordinator):
    """or=19 live data — drives device availability."""

    fail_loud = True

    def __init__(
        self,
        hass: HomeAssistant,
        entry: ConfigEntry,
        client: IBCApiClient,
    ) -> None:
        scan_interval = int(
            entry.options.get(CONF_LIVE_SCAN_INTERVAL, DEFAULT_LIVE_SCAN_INTERVAL)
        )
        super().__init__(
            hass,
            client,
            endpoint_id=ENDPOINT_LIVE,
            fetch_fn=client.async_get_live,
            scan_interval=scan_interval,
        )


class IBCLifetimeCoordinator(IBCEndpointCoordinator):
    """or=6 lifetime counters — fail quiet, ticks at ~hour boundaries anyway."""

    def __init__(
        self,
        hass: HomeAssistant,
        entry: ConfigEntry,
        client: IBCApiClient,
    ) -> None:
        scan_interval = int(
            entry.options.get(
                CONF_LIFETIME_SCAN_INTERVAL, DEFAULT_LIFETIME_SCAN_INTERVAL
            )
        )
        super().__init__(
            hass,
            client,
            endpoint_id=ENDPOINT_LIFETIME,
            fetch_fn=client.async_get_lifetime,
            scan_interval=scan_interval,
        )


class IBCSiccCoordinator(IBCEndpointCoordinator):
    """or=44 flame/SICC diagnostics — fail quiet."""

    def __init__(
        self,
        hass: HomeAssistant,
        entry: ConfigEntry,
        client: IBCApiClient,
    ) -> None:
        scan_interval = int(
            entry.options.get(CONF_SICC_SCAN_INTERVAL, DEFAULT_SICC_SCAN_INTERVAL)
        )
        super().__init__(
            hass,
            client,
            endpoint_id=ENDPOINT_SICC,
            fetch_fn=client.async_get_sicc,
            scan_interval=scan_interval,
        )


class IBCErrorLogCoordinator(IBCEndpointCoordinator):
    """or=7 object_index=1 — most-recent error log entry + event firing.

    Holds the decoded message / raw entry on itself so the `last_error`
    sensor can read them as plain attributes (it doesn't read `data`).
    Fires `ibc_boiler_error_logged` on entry-tuple change; the first
    observation after restart is the baseline and is silent.
    """

    def __init__(
        self,
        hass: HomeAssistant,
        entry: ConfigEntry,
        client: IBCApiClient,
    ) -> None:
        scan_interval = int(
            entry.options.get(
                CONF_ERROR_LOG_SCAN_INTERVAL, DEFAULT_ERROR_LOG_SCAN_INTERVAL
            )
        )
        super().__init__(
            hass,
            client,
            endpoint_id=ENDPOINT_ERROR_LOG,
            fetch_fn=self._fetch_log_entry,
            scan_interval=scan_interval,
        )
        self._entry = entry

        # Model identifiers — set by __init__.py after the info fetch so
        # the decoder can apply combi/G3/large-boiler overrides.
        self.model: str | None = None
        self.model_num: int | None = None

        # Latest decoded log entry, exposed to sensors.
        self.last_error_entry: dict[str, Any] | None = None
        self.last_error_message: str | None = None
        self._last_error_key: tuple | None = None
        # The very first observation after startup is the baseline — we
        # don't fire an event for it, otherwise restarting HA would
        # re-trigger the most recent stale error every time.
        self._baseline_set = False

    def set_model_info(self, *, model: str | None, model_num: int | None) -> None:
        """Provide model info gathered at setup; affects decoded message text."""
        self.model = model
        self.model_num = model_num
        if self.last_error_entry is not None:
            self.last_error_message = decode_error_entry(
                self.last_error_entry, model=self.model, model_num=self.model_num
            )

    async def _fetch_log_entry(self) -> dict[str, Any]:
        entry = await self._client.async_query(OR_ERROR_LOG, object_index=1)
        self._process_log_entry(entry)
        return entry

    def _process_log_entry(self, entry: dict[str, Any]) -> None:
        if is_empty_slot(entry):
            self._baseline_set = True
            return

        key = _entry_key(entry)
        message = decode_error_entry(
            entry, model=self.model, model_num=self.model_num
        )
        self.last_error_entry = entry
        self.last_error_message = message

        if not self._baseline_set:
            self._last_error_key = key
            self._baseline_set = True
            return

        if key != self._last_error_key:
            self._last_error_key = key
            self._fire_event(entry, message)

    def _fire_event(self, entry: dict[str, Any], message: str) -> None:
        date = str(entry.get("Date") or "")
        time = str(entry.get("Time") or "")
        payload = {
            "entry_id": self._entry.entry_id,
            "device_unique_id": self._entry.unique_id,
            "log_no": entry.get("log_no"),
            "date": date,
            "time": time,
            "datetime": f"{date} {time}".strip(),
            "message": message,
            "major_err": entry.get("MajErr"),
            "minor_err": entry.get("MinErr"),
            "system_err": entry.get("SysErr"),
            "combi_err": entry.get("CombiErr"),
            "sim_status": entry.get("SIM_Status"),
            "fan_rpm": entry.get("FanRPM"),
            "flame_sense": entry.get("FlameSense"),
            "inlet_temp_c": _temp_c(entry.get("InletTemp")),
            "outlet_temp_c": _temp_c(entry.get("OutletTemp")),
            "board_temp_c": _temp_c(entry.get("BoardTemp")),
            "inlet_pressure_psi": _pressure_psi(entry.get("InletPressure")),
        }
        _LOGGER.info(
            "IBC boiler logged a new error: %s @ %s",
            message,
            payload["datetime"],
        )
        self.hass.bus.async_fire(EVENT_ERROR_LOGGED, payload)


@dataclass
class IBCRuntimeData:
    """All per-entry state, attached to ConfigEntry.runtime_data."""

    client: IBCApiClient
    coordinators: dict[str, IBCEndpointCoordinator]
    info: dict[str, Any]
    network: dict[str, Any]

    @property
    def live(self) -> IBCLiveCoordinator:
        return self.coordinators[ENDPOINT_LIVE]  # type: ignore[return-value]

    @property
    def error_log(self) -> IBCErrorLogCoordinator:
        return self.coordinators[ENDPOINT_ERROR_LOG]  # type: ignore[return-value]


IBCConfigEntry: TypeAlias = ConfigEntry[IBCRuntimeData]
