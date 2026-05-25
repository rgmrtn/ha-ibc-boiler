"""Constants for the IBC Boiler integration."""

from __future__ import annotations

from enum import IntEnum
from typing import Final

from homeassistant.const import Platform

DOMAIN: Final = "ibc_boiler"
PLATFORMS: Final[list[Platform]] = [Platform.SENSOR, Platform.BINARY_SENSOR]

CONF_HOST: Final = "host"

# Per-endpoint scan intervals (v0.4+). One coordinator per endpoint, polled
# independently — see plan-v0.4.md / plan-v0.5.md.
CONF_LIVE_SCAN_INTERVAL: Final = "live_scan_interval"
CONF_ERROR_LOG_SCAN_INTERVAL: Final = "error_log_scan_interval"
CONF_LIFETIME_SCAN_INTERVAL: Final = "lifetime_scan_interval"
CONF_SICC_SCAN_INTERVAL: Final = "sicc_scan_interval"
CONF_LOAD_RUNTIME_SCAN_INTERVAL: Final = "load_runtime_scan_interval"

DEFAULT_LIVE_SCAN_INTERVAL: Final = 30
DEFAULT_ERROR_LOG_SCAN_INTERVAL: Final = 60
DEFAULT_LIFETIME_SCAN_INTERVAL: Final = 300
DEFAULT_SICC_SCAN_INTERVAL: Final = 30
DEFAULT_LOAD_RUNTIME_SCAN_INTERVAL: Final = 30

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
#   6  - lifetime counters (PowerOnHrs, BurnerOnHrs, Starts, Trials, Errors, Warnings, LogEntries, LoadXOnTime)
#   7  - error/event log entry (per object_index 1..35; 1 = most recent)
#   11 - device info (model, fwversion, fwdate, imperial, boiler_id, sicc_module)
#   13 - per-load type/emitter enumeration (LoadXType, LoadXEmitter, SBnEnable)
#   16 - per-load configuration (request uses object_index for read; shape depends on LoadType)
#   19 - live data (Status, MBH, SupplyT/ReturnT/TargetT, pressures, errors, Servicing bitfield)
#   32 - per-load runtime (Type, HeatOut, SupplyT, ReturnT, Cycles, ...) request uses load_no
#   34 - network info (mac, ipaddr, site_name, boiler_id)
#   44 - flame/SIP/FCP diagnostics (SIP_FlameCurrent, FCP_Power, SIP_Online, ...)
OR_LIFETIME: Final = 6
OR_ERROR_LOG: Final = 7
OR_INFO: Final = 11
OR_LOAD_ENUM: Final = 13
OR_LOAD_CONFIG: Final = 16
OR_LIVE: Final = 19
OR_LOAD_RUNTIME: Final = 32
OR_NETWORK: Final = 34
OR_SICC: Final = 44

# Endpoint identifiers used to key per-endpoint coordinators + sensor
# descriptions. Keep stable — sensor descriptions reference them directly.
ENDPOINT_LIVE: Final = "live"
ENDPOINT_ERROR_LOG: Final = "error_log"
ENDPOINT_LIFETIME: Final = "lifetime"
ENDPOINT_SICC: Final = "sicc"
ENDPOINT_LOAD_RUNTIME: Final = "load_runtime"

# HA event fired when a new entry appears in the boiler's error log.
# Listeners receive the decoded message + raw fields; see README.
EVENT_ERROR_LOGGED: Final = "ibc_boiler_error_logged"

# Sensor sentinel for "not connected" / "not available" returned by the V-10
# controller when a probe has no reading (e.g. outdoor sensor not wired).
NOT_CONNECTED_SENTINEL: Final = -32766

# Number of physical loads on the current V-10 firmware (≥ 2.01). Used to
# bound the or=13 enumeration and the Servicing bitfield decode in or=19.
MAX_LOADS: Final = 5


class LoadType(IntEnum):
    """Per-load mode from or=13 / or=16 `LoadType`.

    Values 0..6 come from `LoadNameFromNum()` in `custom/js/ibc-cmn.js`.
    Value 7 ("On-Demand DHW") is used on Load 5 of combi boilers
    (model_num 23/24) but is not named through `LoadNameFromNum` — the
    UI labels it directly.
    """

    OFF = 0
    DHW = 1
    RESET_HEATING = 2
    SET_POINT = 3
    EXTERNAL_CONTROL = 4
    MANUAL_CONTROL = 5
    ZONE_OF = 6
    ON_DEMAND_DHW = 7


LOAD_TYPE_NAMES: Final[dict[int, str]] = {
    LoadType.OFF: "Off",
    LoadType.DHW: "DHW",
    LoadType.RESET_HEATING: "Reset Heating",
    LoadType.SET_POINT: "Set Point",
    LoadType.EXTERNAL_CONTROL: "External Control",
    LoadType.MANUAL_CONTROL: "Manual Control",
    LoadType.ZONE_OF: "Zone Of",
    LoadType.ON_DEMAND_DHW: "On-Demand DHW",
}

# LoadTypes for which we have a confirmed or=16 schema and surface its config
# sensors. Other types still get a per-load device + runtime sensors + the
# Servicing-derived binary sensors; we just skip the or=16 fetch.
SUPPORTED_LOAD_CONFIG_TYPES: Final[frozenset[int]] = frozenset(
    {LoadType.SET_POINT, LoadType.ON_DEMAND_DHW}
)
