"""Async HTTP client for IBC V-10-platform boilers (bc2-cgi endpoint)."""

from __future__ import annotations

import asyncio
import json
import logging
import re
from typing import Any

import aiohttp
from homeassistant.core import HomeAssistant
from homeassistant.helpers.aiohttp_client import async_get_clientsession

from .const import (
    HTTP_TIMEOUT_SECONDS,
    OBJECT_NO_DEFAULT,
    OR_INFO,
    OR_LIVE,
    OR_NETWORK,
)

_LOGGER = logging.getLogger(__name__)

_HEADERS = {
    "Accept": "application/json",
    "User-Agent": "HomeAssistant-IBCBoiler/0.1",
}

_SCHEME_RX = re.compile(r"^https?://", re.IGNORECASE)


def normalize_host(host: str) -> str:
    """Strip whitespace, scheme, trailing slash, and any path the user pasted in.

    Accepts the things users naturally copy from a browser
    (`http://1.2.3.4/`, `1.2.3.4/index.php`, etc.) and reduces to the
    authority (`host[:port]`) we need to build the CGI URL.
    """
    cleaned = _SCHEME_RX.sub("", host.strip()).strip("/").lower()
    return cleaned.split("/", 1)[0]


class IBCApiError(Exception):
    """Base error for IBC boiler API failures."""


class IBCConnectionError(IBCApiError):
    """Cannot reach the boiler (network, timeout, DNS, refused)."""


class IBCResponseError(IBCApiError):
    """Boiler responded but the response was not usable."""


class IBCAuthError(IBCApiError):
    """Reserved for the unlikely 401/403; bc2-cgi does not currently require auth."""


class IBCApiClient:
    """Talks to a single IBC boiler's local bc2-cgi endpoint."""

    def __init__(self, hass: HomeAssistant, host: str) -> None:
        self._host = normalize_host(host)
        self._session = async_get_clientsession(hass)
        self._url = f"http://{self._host}/cgi-bin/bc2-cgi"

    @property
    def host(self) -> str:
        return self._host

    async def async_query(
        self,
        object_request: int,
        *,
        object_no: int = OBJECT_NO_DEFAULT,
        boiler_no: int = 0,
        object_index: int | None = None,
        load_no: int | None = None,
    ) -> dict[str, Any]:
        """Issue one bc2-cgi query and return the parsed JSON dict.

        The V-10 controller responds to a GET whose `json` query parameter is a
        compact JSON object identifying which object to dump. See docs/protocol.md.
        """
        payload: dict[str, Any] = {
            "object_no": object_no,
            "object_request": object_request,
            "boiler_no": boiler_no,
        }
        if object_index is not None:
            payload["object_index"] = object_index
        if load_no is not None:
            payload["load_no"] = load_no

        timeout = aiohttp.ClientTimeout(total=HTTP_TIMEOUT_SECONDS)
        params = {"json": json.dumps(payload, separators=(",", ":"))}

        try:
            async with self._session.get(
                self._url,
                params=params,
                headers=_HEADERS,
                timeout=timeout,
            ) as resp:
                if resp.status in (401, 403):
                    raise IBCAuthError(f"Unexpected auth challenge: HTTP {resp.status}")
                if resp.status >= 400:
                    raise IBCResponseError(f"HTTP {resp.status} from boiler")
                text = await resp.text()
        except (aiohttp.ClientError, asyncio.TimeoutError, OSError) as err:
            raise IBCConnectionError(str(err) or err.__class__.__name__) from err

        try:
            data = json.loads(text)
        except json.JSONDecodeError as err:
            _LOGGER.debug("Non-JSON response from %s: %r", self._url, text[:200])
            raise IBCResponseError("invalid_json") from err

        if not isinstance(data, dict) or not data:
            raise IBCResponseError("empty_payload")

        # The boiler echoes "fail_code" only on error envelopes. A successful
        # response has "dump" set to the object_request we asked for.
        fail_code = data.get("fail_code")
        if fail_code is not None and fail_code != 0:
            raise IBCResponseError(
                f"boiler rejected object_request={object_request} "
                f"(fail_code={fail_code})"
            )

        dump = data.get("dump")
        if dump is not None and dump != object_request:
            raise IBCResponseError(
                f"boiler returned dump={dump} for object_request={object_request}"
            )

        return data

    async def async_get_live(self) -> dict[str, Any]:
        """Live runtime status — poll this on every coordinator tick."""
        return await self.async_query(OR_LIVE)

    async def async_get_info(self) -> dict[str, Any]:
        """Static device info (model, firmware) — fetch once at setup."""
        return await self.async_query(OR_INFO)

    async def async_get_network(self) -> dict[str, Any]:
        """Network identity (MAC, IP, site name) — fetch once at setup."""
        return await self.async_query(OR_NETWORK)

    async def async_test_connection(self) -> dict[str, Any]:
        """Used by the config flow to confirm the host is a V-10 boiler.

        Returns the device-info payload so the flow can read the MAC + model.
        """
        return await self.async_get_info()
