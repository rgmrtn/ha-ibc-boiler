"""Constants for the IBC Boiler integration."""

from __future__ import annotations

from typing import Final

from homeassistant.const import Platform

DOMAIN: Final = "ibc_boiler"
PLATFORMS: Final[list[Platform]] = [Platform.SENSOR]

CONF_HOST: Final = "host"

# Per-endpoint scan intervals (v0.4+). One coordinator per endpoint, polled
# independently — see plan-v0.4.md.
CONF_LIVE_SCAN_INTERVAL: Final = "live_scan_interval"
CONF_ERROR_LOG_SCAN_INTERVAL: Final = "error_log_scan_interval"
CONF_LIFETIME_SCAN_INTERVAL: Final = "lifetime_scan_interval"
CONF_SICC_SCAN_INTERVAL: Final = "sicc_scan_interval"

DEFAULT_LIVE_SCAN_INTERVAL: Final = 30
DEFAULT_ERROR_LOG_SCAN_INTERVAL: Final = 60
DEFAULT_LIFETIME_SCAN_INTERVAL: Final = 300
DEFAULT_SICC_SCAN_INTERVAL: Final = 30

MIN_SCAN_INTERVAL: Final = 10
MAX_SCAN_INTERVAL: Final = 3600

# Legacy single-interval key — kept only so async_migrate_entry can read it
# off existing v1 config entries and translate it forward.
CONF_SCAN_INTERVAL: Final = "scan_interval"

HTTP_TIMEOUT_SECONDS: Final = 10

MANUFACTURER: Final = "IBC Technologies"
DEFAULT_MODEL: Final = "V-10 Boiler"

# V-10 protocol — see docs/protocol.md.
# object_no=100 is the only object_no we've ever observed; everything else is
# selected by object_request.
OBJECT_NO_DEFAULT: Final = 100

# object_request codes we use:
#   6  - lifetime counters (PowerOnHrs, BurnerOnHrs, Starts, Trials, Errors, Warnings, LogEntries)
#   7  - error/event log entry (per object_index 1..35; 1 = most recent)
#   11 - device info (model, fwversion, fwdate, imperial, boiler_id, sicc_module)
#   19 - live data (Status, MBH, SupplyT/ReturnT/TargetT, pressures, errors)
#   34 - network info (mac, ipaddr, site_name, boiler_id)
#   44 - flame/SIP/FCP diagnostics (SIP_FlameCurrent, FCP_Power, SIP_Online, ...)
OR_LIFETIME: Final = 6
OR_ERROR_LOG: Final = 7
OR_INFO: Final = 11
OR_LIVE: Final = 19
OR_NETWORK: Final = 34
OR_SICC: Final = 44

# Endpoint identifiers used to key per-endpoint coordinators + sensor
# descriptions. Keep stable — sensor descriptions reference them directly.
ENDPOINT_LIVE: Final = "live"
ENDPOINT_ERROR_LOG: Final = "error_log"
ENDPOINT_LIFETIME: Final = "lifetime"
ENDPOINT_SICC: Final = "sicc"

# HA event fired when a new entry appears in the boiler's error log.
# Listeners receive the decoded message + raw fields; see README.
EVENT_ERROR_LOGGED: Final = "ibc_boiler_error_logged"

# Sensor sentinel for "not connected" / "not available" returned by the V-10
# controller when a probe has no reading (e.g. outdoor sensor not wired).
NOT_CONNECTED_SENTINEL: Final = -32766
