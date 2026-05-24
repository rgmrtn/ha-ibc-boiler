"""DataUpdateCoordinator and per-entry runtime data for IBC Boiler."""

from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import timedelta
from typing import Any, TypeAlias

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed

from .api import IBCApiClient, IBCConnectionError, IBCResponseError
from .const import (
    CONF_SCAN_INTERVAL,
    DEFAULT_SCAN_INTERVAL,
    DOMAIN,
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


class IBCDataUpdateCoordinator(DataUpdateCoordinator[dict[str, Any]]):
    """Polls the boiler's live-data object (or=19) on every tick.

    Also opportunistically fetches the most recent error log entry
    (or=7 object_index=1) on the same tick. A failure on the log fetch
    is logged but does not fail the update — live data is the source of
    truth for "is the boiler reachable".
    """

    def __init__(
        self,
        hass: HomeAssistant,
        entry: ConfigEntry,
        client: IBCApiClient,
    ) -> None:
        scan_interval = entry.options.get(CONF_SCAN_INTERVAL, DEFAULT_SCAN_INTERVAL)
        super().__init__(
            hass,
            _LOGGER,
            name=f"{DOMAIN} {client.host}",
            update_interval=timedelta(seconds=scan_interval),
        )
        self._client = client
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
        # If we polled or=7 before model info was set, redecode so the
        # sensor shows the model-correct message without waiting a tick.
        if self.last_error_entry is not None:
            self.last_error_message = decode_error_entry(
                self.last_error_entry, model=self.model, model_num=self.model_num
            )

    async def _async_update_data(self) -> dict[str, Any]:
        try:
            live = await self._client.async_get_live()
        except IBCConnectionError as err:
            raise UpdateFailed(f"Cannot reach boiler: {err}") from err
        except IBCResponseError as err:
            raise UpdateFailed(f"Bad response from boiler: {err}") from err

        # Best-effort log poll. Don't let a failure here mask live data.
        try:
            log_entry = await self._client.async_query(
                OR_ERROR_LOG, object_index=1
            )
        except (IBCConnectionError, IBCResponseError) as err:
            _LOGGER.debug("error-log fetch (or=7 idx=1) failed: %s", err)
        else:
            self._process_log_entry(log_entry)

        return live

    def _process_log_entry(self, entry: dict[str, Any]) -> None:
        if is_empty_slot(entry):
            # Brand-new boiler / fresh log — nothing to surface, but still
            # mark the baseline so a future first event fires.
            self._baseline_set = True
            return

        key = _entry_key(entry)
        message = decode_error_entry(
            entry, model=self.model, model_num=self.model_num
        )
        self.last_error_entry = entry
        self.last_error_message = message

        if not self._baseline_set:
            # First observation after restart/setup — anchor without firing.
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
    coordinator: IBCDataUpdateCoordinator
    info: dict[str, Any]
    network: dict[str, Any]


IBCConfigEntry: TypeAlias = ConfigEntry[IBCRuntimeData]
