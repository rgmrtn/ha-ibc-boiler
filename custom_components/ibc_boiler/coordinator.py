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
from .const import CONF_SCAN_INTERVAL, DEFAULT_SCAN_INTERVAL, DOMAIN

_LOGGER = logging.getLogger(__name__)


class IBCDataUpdateCoordinator(DataUpdateCoordinator[dict[str, Any]]):
    """Polls the boiler's live-data object (or=19) on every tick."""

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

    async def _async_update_data(self) -> dict[str, Any]:
        try:
            return await self._client.async_get_live()
        except IBCConnectionError as err:
            raise UpdateFailed(f"Cannot reach boiler: {err}") from err
        except IBCResponseError as err:
            raise UpdateFailed(f"Bad response from boiler: {err}") from err


@dataclass
class IBCRuntimeData:
    """All per-entry state, attached to ConfigEntry.runtime_data."""

    client: IBCApiClient
    coordinator: IBCDataUpdateCoordinator
    info: dict[str, Any]
    network: dict[str, Any]


IBCConfigEntry: TypeAlias = ConfigEntry[IBCRuntimeData]
