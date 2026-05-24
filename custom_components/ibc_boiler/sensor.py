"""Sensor platform for IBC V-10-platform boilers (object_request 19)."""

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
    UnitOfPressure,
    UnitOfTemperature,
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
    MANUFACTURER,
    NOT_CONNECTED_SENTINEL,
)
from .coordinator import IBCConfigEntry, IBCDataUpdateCoordinator, IBCRuntimeData


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


@dataclass(frozen=True, kw_only=True)
class IBCSensorEntityDescription(SensorEntityDescription):
    """SensorEntityDescription with a value extractor over the live-data dict."""

    value_fn: Callable[[dict[str, Any]], StateType]


SENSOR_DESCRIPTIONS: tuple[IBCSensorEntityDescription, ...] = (
    IBCSensorEntityDescription(
        key="supply_temp",
        translation_key="supply_temp",
        device_class=SensorDeviceClass.TEMPERATURE,
        state_class=SensorStateClass.MEASUREMENT,
        native_unit_of_measurement=UnitOfTemperature.CELSIUS,
        value_fn=lambda d: _temp(d.get("SupplyT")),
    ),
    IBCSensorEntityDescription(
        key="return_temp",
        translation_key="return_temp",
        device_class=SensorDeviceClass.TEMPERATURE,
        state_class=SensorStateClass.MEASUREMENT,
        native_unit_of_measurement=UnitOfTemperature.CELSIUS,
        value_fn=lambda d: _temp(d.get("ReturnT")),
    ),
    IBCSensorEntityDescription(
        key="target_temp",
        translation_key="target_temp",
        device_class=SensorDeviceClass.TEMPERATURE,
        state_class=SensorStateClass.MEASUREMENT,
        native_unit_of_measurement=UnitOfTemperature.CELSIUS,
        value_fn=lambda d: _temp(d.get("TargetT")),
    ),
    IBCSensorEntityDescription(
        key="stack_temp",
        translation_key="stack_temp",
        device_class=SensorDeviceClass.TEMPERATURE,
        state_class=SensorStateClass.MEASUREMENT,
        native_unit_of_measurement=UnitOfTemperature.CELSIUS,
        value_fn=lambda d: _temp(d.get("StackT")),
    ),
    IBCSensorEntityDescription(
        key="outdoor_temp",
        translation_key="outdoor_temp",
        device_class=SensorDeviceClass.TEMPERATURE,
        state_class=SensorStateClass.MEASUREMENT,
        native_unit_of_measurement=UnitOfTemperature.CELSIUS,
        value_fn=lambda d: _temp(d.get("OutdoorT")),
    ),
    IBCSensorEntityDescription(
        key="indoor_temp",
        translation_key="indoor_temp",
        device_class=SensorDeviceClass.TEMPERATURE,
        state_class=SensorStateClass.MEASUREMENT,
        native_unit_of_measurement=UnitOfTemperature.CELSIUS,
        value_fn=lambda d: _temp(d.get("IndoorT")),
    ),
    IBCSensorEntityDescription(
        key="tank_temp",
        translation_key="tank_temp",
        device_class=SensorDeviceClass.TEMPERATURE,
        state_class=SensorStateClass.MEASUREMENT,
        native_unit_of_measurement=UnitOfTemperature.CELSIUS,
        value_fn=lambda d: _temp(d.get("TankT")),
    ),
    IBCSensorEntityDescription(
        key="inlet_pressure",
        translation_key="inlet_pressure",
        device_class=SensorDeviceClass.PRESSURE,
        state_class=SensorStateClass.MEASUREMENT,
        native_unit_of_measurement=UnitOfPressure.PSI,
        value_fn=lambda d: _pressure(d.get("InletPressure")),
    ),
    IBCSensorEntityDescription(
        key="outlet_pressure",
        translation_key="outlet_pressure",
        device_class=SensorDeviceClass.PRESSURE,
        state_class=SensorStateClass.MEASUREMENT,
        native_unit_of_measurement=UnitOfPressure.PSI,
        value_fn=lambda d: _pressure(d.get("OutletPressure")),
    ),
    IBCSensorEntityDescription(
        key="delta_pressure",
        translation_key="delta_pressure",
        device_class=SensorDeviceClass.PRESSURE,
        state_class=SensorStateClass.MEASUREMENT,
        native_unit_of_measurement=UnitOfPressure.PSI,
        value_fn=lambda d: _pressure(d.get("DeltaPressure")),
    ),
    IBCSensorEntityDescription(
        key="power_output",
        translation_key="power_output",
        state_class=SensorStateClass.MEASUREMENT,
        native_unit_of_measurement="MBH",
        value_fn=lambda d: _as_float(d.get("MBH")),
    ),
    IBCSensorEntityDescription(
        key="cycles",
        translation_key="cycles",
        state_class=SensorStateClass.TOTAL_INCREASING,
        entity_category=EntityCategory.DIAGNOSTIC,
        value_fn=lambda d: _as_int(d.get("Cycles")),
    ),
    IBCSensorEntityDescription(
        key="status",
        translation_key="status",
        entity_category=EntityCategory.DIAGNOSTIC,
        value_fn=lambda d: _str_or_none(d.get("Status")),
    ),
    IBCSensorEntityDescription(
        key="error_code",
        translation_key="error_code",
        entity_category=EntityCategory.DIAGNOSTIC,
        value_fn=lambda d: _as_int(d.get("ErrorCode")),
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
        IBCSensor(runtime.coordinator, entry, description, device_info)
        for description in SENSOR_DESCRIPTIONS
    ]
    entities.append(IBCLastErrorSensor(runtime.coordinator, entry, device_info))
    async_add_entities(entities)


class IBCSensor(CoordinatorEntity[IBCDataUpdateCoordinator], SensorEntity):
    """A single sensor backed by a value_fn over the live-data dict."""

    _attr_has_entity_name = True
    entity_description: IBCSensorEntityDescription

    def __init__(
        self,
        coordinator: IBCDataUpdateCoordinator,
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


class IBCLastErrorSensor(CoordinatorEntity[IBCDataUpdateCoordinator], SensorEntity):
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
        coordinator: IBCDataUpdateCoordinator,
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
