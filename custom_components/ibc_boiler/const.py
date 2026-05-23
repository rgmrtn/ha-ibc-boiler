"""Constants for the IBC Boiler integration."""

from __future__ import annotations

from typing import Final

from homeassistant.const import Platform

DOMAIN: Final = "ibc_boiler"
PLATFORMS: Final[list[Platform]] = [Platform.SENSOR]

CONF_HOST: Final = "host"
CONF_SCAN_INTERVAL: Final = "scan_interval"

DEFAULT_SCAN_INTERVAL: Final = 30
MIN_SCAN_INTERVAL: Final = 10
MAX_SCAN_INTERVAL: Final = 600

HTTP_TIMEOUT_SECONDS: Final = 10

MANUFACTURER: Final = "IBC Technologies"
DEFAULT_MODEL: Final = "V-10 Boiler"

# V-10 protocol — see docs/protocol.md.
# object_no=100 is the only object_no we've ever observed; everything else is
# selected by object_request.
OBJECT_NO_DEFAULT: Final = 100

# object_request codes we use:
#   11 - device info (model, fwversion, fwdate, imperial, boiler_id, sicc_module)
#   19 - live data (Status, MBH, SupplyT/ReturnT/TargetT, pressures, errors)
#   34 - network info (mac, ipaddr, site_name, boiler_id)
OR_INFO: Final = 11
OR_LIVE: Final = 19
OR_NETWORK: Final = 34

# Sensor sentinel for "not connected" / "not available" returned by the V-10
# controller when a probe has no reading (e.g. outdoor sensor not wired).
NOT_CONNECTED_SENTINEL: Final = -32766
