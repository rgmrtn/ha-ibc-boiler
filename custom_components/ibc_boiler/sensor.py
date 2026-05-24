"""Sensor platform for IBC V-10-platform boilers.

Sensors are described declaratively (`IBCSensorEntityDescription`) and each
description names the endpoint coordinator it reads from. v0.4 wires
descriptions to four endpoints: live (or=19), lifetime (or=6), sicc (or=44),
and error log (or=7) — the last one only feeds the dedicated `last_error`
sensor.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

from homeassistant.components.sensor import (
    SensorDeviceClass,
    SensorEntity,
    SensorEntityDescription,
    SensorStateClass,
)
from homeassistant.const import (
    EntityCategory,
    UnitOfElectricCurrent,
    UnitOfPower,
    UnitOfPressure,
    UnitOfTemperature,
    UnitOfTime,
)
from homeassistant.core import HomeAssistant
from homeassistant.helpers.device_registry import (
    CONNECTION_NETWORK_MAC,
    DeviceInfo,
    format_mac,
)
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.typing import StateType
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import (
    CONF_HOST,
    DEFAULT_MODEL,
    DOMAIN,
    ENDPOINT_ERROR_LOG,
    ENDPOINT_LIFETIME,
    ENDPOINT_LIVE,
    ENDPOINT_SICC,
    MANUFACTURER,
    NOT_CONNECTED_SENTINEL,
)
from .coordinator import (
    IBCConfigEntry,
    IBCEndpointCoordinator,
    IBCErrorLogCoordinator,
    IBCRuntimeData,
)


def _as_float(value: Any) -> float | None:
    if value is None:
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _as_int(value: Any) -> int | None:
    f = _as_float(value)
    return None if f is None else int(f)


def _temp(value: Any) -> float | None:
    """Convert a V-10 temperature field to °C.

    All temperatures in the V-10 JSON are stored as **quarter-degrees Celsius**
    (per the boiler's own web UI source: "All temperatures to and from the
    boiler are in °C * 4 (eg. 80 = 20°C)"). HA receives °C and converts to the
    user's display unit; do not attempt °F conversion here.

    The V-10 reports -32766 in any field whose probe is unwired; we drop it.
    """
    f = _as_float(value)
    if f is None or f == NOT_CONNECTED_SENTINEL:
        return None
    return f / 4


def _pressure(value: Any) -> float | None:
    """Return psi as float. The V-10 reports psi directly (e.g. 16.6)."""
    return _as_float(value)


def _str_or_none(value: Any) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    return text or None


def _fault_text(value: Any) -> str | None:
    """Live faults/warnings text. The V-10 returns the literal string "None"
    when no fault/warning is asserted — translate to a real None so HA shows
    `unknown` (or the empty state) instead of the misleading word "None"."""
    text = _str_or_none(value)
    if text is None or text.lower() == "none":
        return None
    return text


def _flame_current(value: Any) -> float | None:
    """SIP_FlameCurrent → µA. The boiler's own error.js divides by 249 to
    render the value, so we do the same."""
    f = _as_float(value)
    if f is None:
        return None
    return round(f / 249, 2)


def _online_state(value: Any) -> str | None:
    """SIP_Online → "online" / "offline" text (bool-shaped int)."""
    i = _as_int(value)
    if i is None:
        return None
    return "online" if i else "offline"


@dataclass(frozen=True, kw_only=True)
class IBCSensorEntityDescription(SensorEntityDescription):
    """SensorEntityDescription bound to one endpoint coordinator."""

    endpoint: str
    value_fn: Callable[[dict[str, Any]], StateType]
    # Optional extra state attributes (e.g. raw bitfields for active_faults).
    attributes_fn: Callable[[dict[str, Any]], dict[str, Any] | None] | None = None


def _active_faults_attrs(d: dict[str, Any]) -> dict[str, Any] | None:
    return {
        "major_err": _as_int(d.get("MajorError")),
        "minor_err": _as_int(d.get("MinorError")),
        "system_err": _as_int(d.get("SystemError")),
        "combi_err": _as_int(d.get("CombiError")),
        "warn_flags": _as_int(d.get("WarnFlags")),
    }


SENSOR_DESCRIPTIONS: tuple[IBCSensorEntityDescription, ...] = (
    # ----- Live data (or=19) ------------------------------------------------
    IBCSensorEntityDescription(
        key="supply_temp",
        translation_key="supply_temp",
        endpoint=ENDPOINT_LIVE,
        device_class=SensorDeviceClass.TEMPERATURE,
        state_class=SensorStateClass.MEASUREMENT,
        native_unit_of_measurement=UnitOfTemperature.CELSIUS,
        value_fn=lambda d: _temp(d.get("SupplyT")),
    ),
    IBCSensorEntityDescription(
        key="return_temp",
        translation_key="return_temp",
        endpoint=ENDPOINT_LIVE,
        device_class=SensorDeviceClass.TEMPERATURE,
        state_class=SensorStateClass.MEASUREMENT,
        native_unit_of_measurement=UnitOfTemperature.CELSIUS,
        value_fn=lambda d: _temp(d.get("ReturnT")),
    ),
    IBCSensorEntityDescription(
        key="target_temp",
        translation_key="target_temp",
        endpoint=ENDPOINT_LIVE,
        device_class=SensorDeviceClass.TEMPERATURE,
        state_class=SensorStateClass.MEASUREMENT,
        native_unit_of_measurement=UnitOfTemperature.CELSIUS,
        value_fn=lambda d: _temp(d.get("TargetT")),
    ),
    IBCSensorEntityDescription(
        key="stack_temp",
        translation_key="stack_temp",
        endpoint=ENDPOINT_LIVE,
        device_class=SensorDeviceClass.TEMPERATURE,
        state_class=SensorStateClass.MEASUREMENT,
        native_unit_of_measurement=UnitOfTemperature.CELSIUS,
        value_fn=lambda d: _temp(d.get("StackT")),
    ),
    IBCSensorEntityDescription(
        key="outdoor_temp",
        translation_key="outdoor_temp",
        endpoint=ENDPOINT_LIVE,
        device_class=SensorDeviceClass.TEMPERATURE,
        state_class=SensorStateClass.MEASUREMENT,
        native_unit_of_measurement=UnitOfTemperature.CELSIUS,
        value_fn=lambda d: _temp(d.get("OutdoorT")),
    ),
    IBCSensorEntityDescription(
        key="indoor_temp",
        translation_key="indoor_temp",
        endpoint=ENDPOINT_LIVE,
        device_class=SensorDeviceClass.TEMPERATURE,
        state_class=SensorStateClass.MEASUREMENT,
        native_unit_of_measurement=UnitOfTemperature.CELSIUS,
        value_fn=lambda d: _temp(d.get("IndoorT")),
    ),
    IBCSensorEntityDescription(
        key="air_temp",
        translation_key="air_temp",
        endpoint=ENDPOINT_LIVE,
        device_class=SensorDeviceClass.TEMPERATURE,
        state_class=SensorStateClass.MEASUREMENT,
        native_unit_of_measurement=UnitOfTemperature.CELSIUS,
        entity_category=EntityCategory.DIAGNOSTIC,
        value_fn=lambda d: _temp(d.get("AirT")),
    ),
    IBCSensorEntityDescription(
        key="secondary_temp",
        translation_key="secondary_temp",
        endpoint=ENDPOINT_LIVE,
        device_class=SensorDeviceClass.TEMPERATURE,
        state_class=SensorStateClass.MEASUREMENT,
        native_unit_of_measurement=UnitOfTemperature.CELSIUS,
        entity_category=EntityCategory.DIAGNOSTIC,
        value_fn=lambda d: _temp(d.get("SecondaryT")),
    ),
    IBCSensorEntityDescription(
        key="inlet_pressure",
        translation_key="inlet_pressure",
        endpoint=ENDPOINT_LIVE,
        device_class=SensorDeviceClass.PRESSURE,
        state_class=SensorStateClass.MEASUREMENT,
        native_unit_of_measurement=UnitOfPressure.PSI,
        value_fn=lambda d: _pressure(d.get("InletPressure")),
    ),
    IBCSensorEntityDescription(
        key="outlet_pressure",
        translation_key="outlet_pressure",
        endpoint=ENDPOINT_LIVE,
        device_class=SensorDeviceClass.PRESSURE,
        state_class=SensorStateClass.MEASUREMENT,
        native_unit_of_measurement=UnitOfPressure.PSI,
        value_fn=lambda d: _pressure(d.get("OutletPressure")),
    ),
    IBCSensorEntityDescription(
        key="delta_pressure",
        translation_key="delta_pressure",
        endpoint=ENDPOINT_LIVE,
        device_class=SensorDeviceClass.PRESSURE,
        state_class=SensorStateClass.MEASUREMENT,
        native_unit_of_measurement=UnitOfPressure.PSI,
        value_fn=lambda d: _pressure(d.get("DeltaPressure")),
    ),
    IBCSensorEntityDescription(
        key="power_output",
        translation_key="power_output",
        endpoint=ENDPOINT_LIVE,
        state_class=SensorStateClass.MEASUREMENT,
        native_unit_of_measurement="MBH",
        value_fn=lambda d: _as_float(d.get("MBH")),
    ),
    IBCSensorEntityDescription(
        key="cycles",
        translation_key="cycles",
        endpoint=ENDPOINT_LIVE,
        state_class=SensorStateClass.TOTAL_INCREASING,
        entity_category=EntityCategory.DIAGNOSTIC,
        value_fn=lambda d: _as_int(d.get("Cycles")),
    ),
    IBCSensorEntityDescription(
        key="status",
        translation_key="status",
        endpoint=ENDPOINT_LIVE,
        entity_category=EntityCategory.DIAGNOSTIC,
        value_fn=lambda d: _str_or_none(d.get("Status")),
    ),
    IBCSensorEntityDescription(
        key="error_code",
        translation_key="error_code",
        endpoint=ENDPOINT_LIVE,
        entity_category=EntityCategory.DIAGNOSTIC,
        value_fn=lambda d: _as_int(d.get("ErrorCode")),
    ),
    IBCSensorEntityDescription(
        key="active_faults",
        translation_key="active_faults",
        endpoint=ENDPOINT_LIVE,
        entity_category=EntityCategory.DIAGNOSTIC,
        value_fn=lambda d: _fault_text(d.get("Errors")),
        attributes_fn=_active_faults_attrs,
    ),
    IBCSensorEntityDescription(
        key="active_warnings",
        translation_key="active_warnings",
        endpoint=ENDPOINT_LIVE,
        entity_category=EntityCategory.DIAGNOSTIC,
        value_fn=lambda d: _fault_text(d.get("Warnings")),
    ),
    # ----- Lifetime counters (or=6) -----------------------------------------
    IBCSensorEntityDescription(
        key="power_on_hours",
        translation_key="power_on_hours",
        endpoint=ENDPOINT_LIFETIME,
        state_class=SensorStateClass.TOTAL_INCREASING,
        native_unit_of_measurement=UnitOfTime.HOURS,
        entity_category=EntityCategory.DIAGNOSTIC,
        value_fn=lambda d: _as_int(d.get("PowerOnHrs")),
    ),
    IBCSensorEntityDescription(
        key="burner_on_hours",
        translation_key="burner_on_hours",
        endpoint=ENDPOINT_LIFETIME,
        state_class=SensorStateClass.TOTAL_INCREASING,
        native_unit_of_measurement=UnitOfTime.HOURS,
        entity_category=EntityCategory.DIAGNOSTIC,
        value_fn=lambda d: _as_int(d.get("BurnerOnHrs")),
    ),
    IBCSensorEntityDescription(
        key="burner_starts",
        translation_key="burner_starts",
        endpoint=ENDPOINT_LIFETIME,
        state_class=SensorStateClass.TOTAL_INCREASING,
        entity_category=EntityCategory.DIAGNOSTIC,
        value_fn=lambda d: _as_int(d.get("Starts")),
    ),
    IBCSensorEntityDescription(
        key="ignition_trials",
        translation_key="ignition_trials",
        endpoint=ENDPOINT_LIFETIME,
        state_class=SensorStateClass.TOTAL_INCREASING,
        entity_category=EntityCategory.DIAGNOSTIC,
        value_fn=lambda d: _as_int(d.get("Trials")),
    ),
    IBCSensorEntityDescription(
        key="lifetime_errors",
        translation_key="lifetime_errors",
        endpoint=ENDPOINT_LIFETIME,
        state_class=SensorStateClass.TOTAL_INCREASING,
        entity_category=EntityCategory.DIAGNOSTIC,
        value_fn=lambda d: _as_int(d.get("Errors")),
    ),
    IBCSensorEntityDescription(
        key="lifetime_warnings",
        translation_key="lifetime_warnings",
        endpoint=ENDPOINT_LIFETIME,
        state_class=SensorStateClass.TOTAL_INCREASING,
        entity_category=EntityCategory.DIAGNOSTIC,
        value_fn=lambda d: _as_int(d.get("Warnings")),
    ),
    IBCSensorEntityDescription(
        key="log_entries",
        translation_key="log_entries",
        endpoint=ENDPOINT_LIFETIME,
        state_class=SensorStateClass.MEASUREMENT,
        entity_category=EntityCategory.DIAGNOSTIC,
        value_fn=lambda d: _as_int(d.get("LogEntries")),
    ),
    # ----- Flame / SICC (or=44) ---------------------------------------------
    IBCSensorEntityDescription(
        key="flame_current",
        translation_key="flame_current",
        endpoint=ENDPOINT_SICC,
        device_class=SensorDeviceClass.CURRENT,
        state_class=SensorStateClass.MEASUREMENT,
        native_unit_of_measurement=UnitOfElectricCurrent.MICROAMPERE,
        entity_category=EntityCategory.DIAGNOSTIC,
        value_fn=lambda d: _flame_current(d.get("SIP_FlameCurrent")),
    ),
    IBCSensorEntityDescription(
        key="sicc_power",
        translation_key="sicc_power",
        endpoint=ENDPOINT_SICC,
        device_class=SensorDeviceClass.POWER,
        state_class=SensorStateClass.MEASUREMENT,
        native_unit_of_measurement=UnitOfPower.WATT,
        entity_category=EntityCategory.DIAGNOSTIC,
        value_fn=lambda d: _as_float(d.get("FCP_Power")),
    ),
    IBCSensorEntityDescription(
        key="sicc_online",
        translation_key="sicc_online",
        endpoint=ENDPOINT_SICC,
        entity_category=EntityCategory.DIAGNOSTIC,
        value_fn=lambda d: _online_state(d.get("SIP_Online")),
    ),
)


def _build_device_info(entry: IBCConfigEntry, runtime: IBCRuntimeData) -> DeviceInfo:
    info = runtime.info or {}
    network = runtime.network or {}

    model = _str_or_none(info.get("model")) or DEFAULT_MODEL
    sw_version_parts = [
        _str_or_none(info.get("fwversion")),
        _str_or_none(info.get("fwdate")),
    ]
    sw_version = " ".join(p for p in sw_version_parts if p) or None
    mac_raw = _str_or_none(network.get("mac"))
    mac = format_mac(mac_raw) if mac_raw else None
    site_name = _str_or_none(network.get("site_name"))

    name = site_name or entry.title

    device = DeviceInfo(
        identifiers={(DOMAIN, entry.unique_id or entry.entry_id)},
        name=name,
        manufacturer=MANUFACTURER,
        model=model,
        configuration_url=f"http://{entry.data[CONF_HOST]}/",
    )
    if sw_version:
        device["sw_version"] = sw_version
    if mac:
        device["connections"] = {(CONNECTION_NETWORK_MAC, mac)}
    return device


async def async_setup_entry(
    hass: HomeAssistant,
    entry: IBCConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    runtime = entry.runtime_data
    device_info = _build_device_info(entry, runtime)

    entities: list[SensorEntity] = [
        IBCSensor(
            runtime.coordinators[description.endpoint],
            entry,
            description,
            device_info,
        )
        for description in SENSOR_DESCRIPTIONS
    ]
    entities.append(
        IBCLastErrorSensor(
            runtime.coordinators[ENDPOINT_ERROR_LOG],  # type: ignore[arg-type]
            entry,
            device_info,
        )
    )
    async_add_entities(entities)


class IBCSensor(CoordinatorEntity[IBCEndpointCoordinator], SensorEntity):
    """A single sensor backed by a value_fn over its coordinator's payload."""

    _attr_has_entity_name = True
    entity_description: IBCSensorEntityDescription

    def __init__(
        self,
        coordinator: IBCEndpointCoordinator,
        entry: IBCConfigEntry,
        description: IBCSensorEntityDescription,
        device_info: DeviceInfo,
    ) -> None:
        super().__init__(coordinator)
        self.entity_description = description
        self._attr_unique_id = f"{entry.unique_id or entry.entry_id}_{description.key}"
        self._attr_device_info = device_info

    @property
    def native_value(self) -> StateType:
        data = self.coordinator.data
        if not isinstance(data, dict):
            return None
        return self.entity_description.value_fn(data)

    @property
    def extra_state_attributes(self) -> dict[str, Any] | None:
        attrs_fn = self.entity_description.attributes_fn
        if attrs_fn is None:
            return None
        data = self.coordinator.data
        if not isinstance(data, dict):
            return None
        return attrs_fn(data)


class IBCLastErrorSensor(CoordinatorEntity[IBCErrorLogCoordinator], SensorEntity):
    """Most-recent boiler error log entry (object_request 7, object_index 1).

    State is the decoded message that matches the boiler's own web UI.
    Raw fields and a combined datetime are exposed as attributes so a
    notification template can render anything the user wants.

    For new-error *notifications* prefer listening to the
    `ibc_boiler_error_logged` event — it fires only on a state change and
    carries the same payload as this sensor's attributes.
    """

    _attr_has_entity_name = True
    _attr_translation_key = "last_error"
    _attr_entity_category = EntityCategory.DIAGNOSTIC
    _attr_icon = "mdi:alert-circle-outline"

    def __init__(
        self,
        coordinator: IBCErrorLogCoordinator,
        entry: IBCConfigEntry,
        device_info: DeviceInfo,
    ) -> None:
        super().__init__(coordinator)
        self._attr_unique_id = f"{entry.unique_id or entry.entry_id}_last_error"
        self._attr_device_info = device_info

    @property
    def native_value(self) -> StateType:
        msg = self.coordinator.last_error_message
        if msg is None:
            return None
        # HA caps state strings at 255 chars; multiple simultaneous
        # faults are joined with "; " and almost always fit, but guard
        # anyway so an unusual concatenation doesn't break the entity.
        return msg if len(msg) <= 255 else msg[:252] + "..."

    @property
    def extra_state_attributes(self) -> dict[str, Any] | None:
        entry = self.coordinator.last_error_entry
        if not entry:
            return None
        date = _str_or_none(entry.get("Date"))
        time = _str_or_none(entry.get("Time"))
        datetime_str = " ".join(p for p in (date, time) if p) or None
        return {
            "log_no": _as_int(entry.get("log_no")),
            "datetime": datetime_str,
            "date": date,
            "time": time,
            "major_err": _as_int(entry.get("MajErr")),
            "minor_err": _as_int(entry.get("MinErr")),
            "system_err": _as_int(entry.get("SysErr")),
            "combi_err": _as_int(entry.get("CombiErr")),
            "sim_status": _as_int(entry.get("SIM_Status")),
            "fan_rpm": _as_int(entry.get("FanRPM")),
            "flame_sense": _as_int(entry.get("FlameSense")),
            "inlet_temp_c": _temp(entry.get("InletTemp")),
            "outlet_temp_c": _temp(entry.get("OutletTemp")),
            "board_temp_c": _temp(entry.get("BoardTemp")),
            # or=7 reports pressure as integer tenths of psi (unlike or=19
            # which is already decimal psi). See docs/protocol.md.
            "inlet_pressure_psi": (
                _as_float(entry.get("InletPressure")) / 10
                if entry.get("InletPressure") is not None
                else None
            ),
        }
