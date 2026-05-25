"""Binary sensor platform for IBC V-10-platform boilers.

v0.5 introduces three families of binary sensor:

- **Per-load (one set per enabled load):** decoded from the `Servicing`
  bitfield in or=19 — Circulating (pump), Calling (demand), Servicing
  (service mode). All three come from the existing live coordinator, so
  no extra HTTP cost.
- **Boiler-level summer_off / remote_mode:** whole-field interpretations
  of the same `Servicing` integer.
- **Boiler-level sicc_online:** from or=44 `SIP_Online`. Replaces the v0.4
  text sensor with `BinarySensorDeviceClass.CONNECTIVITY`. The
  translation key (`sicc_online`) is reused — the entity_id changes
  domain (`sensor.*` → `binary_sensor.*`), so this is a breaking change
  for any automation that referenced the old text sensor.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

from homeassistant.components.binary_sensor import (
    BinarySensorDeviceClass,
    BinarySensorEntity,
    BinarySensorEntityDescription,
)
from homeassistant.const import EntityCategory
from homeassistant.core import HomeAssistant
from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import (
    ENDPOINT_LIVE,
    ENDPOINT_SICC,
)
from .coordinator import IBCConfigEntry, IBCEndpointCoordinator
from .devices import (
    boiler_device_info,
    boiler_unique_id,
    load_device_info,
    load_entity_unique_id,
)


def _as_int(value: Any) -> int | None:
    if value is None:
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


# ---------------------------------------------------------------------------
# Per-load: bits in or=19's Servicing integer
# ---------------------------------------------------------------------------
#
# bit (load_no - 1)        → load is in service mode
# bit (load_no - 1) + 8    → load pump is circulating  (pump on)
# bit (load_no - 1) + 16   → load is calling for heat
#
# Source: custom/js/index.js:428-449 — see docs/protocol.md.

_PUMP_BIT_SHIFT = 8
_CALLING_BIT_SHIFT = 16
_SERVICING_BIT_SHIFT = 0


def _bit_fn(shift: int) -> Callable[[dict[str, Any], int], bool | None]:
    def _read(data: dict[str, Any], load_no: int) -> bool | None:
        servicing = _as_int(data.get("Servicing"))
        if servicing is None:
            return None
        return bool(servicing & (1 << (load_no - 1 + shift)))

    return _read


@dataclass(frozen=True, kw_only=True)
class IBCLoadBinarySensorDescription(BinarySensorEntityDescription):
    """Per-load binary sensor description (live coordinator only)."""

    is_on_fn: Callable[[dict[str, Any], int], bool | None]


LOAD_BINARY_DESCRIPTIONS: tuple[IBCLoadBinarySensorDescription, ...] = (
    IBCLoadBinarySensorDescription(
        key="load_pump",
        translation_key="load_pump",
        device_class=BinarySensorDeviceClass.RUNNING,
        is_on_fn=_bit_fn(_PUMP_BIT_SHIFT),
    ),
    IBCLoadBinarySensorDescription(
        key="load_calling",
        translation_key="load_calling",
        device_class=BinarySensorDeviceClass.HEAT,
        is_on_fn=_bit_fn(_CALLING_BIT_SHIFT),
    ),
    IBCLoadBinarySensorDescription(
        key="load_servicing",
        translation_key="load_servicing",
        device_class=BinarySensorDeviceClass.RUNNING,
        entity_category=EntityCategory.DIAGNOSTIC,
        is_on_fn=_bit_fn(_SERVICING_BIT_SHIFT),
    ),
)


# ---------------------------------------------------------------------------
# Boiler-level binary sensors
# ---------------------------------------------------------------------------


@dataclass(frozen=True, kw_only=True)
class IBCBoilerBinarySensorDescription(BinarySensorEntityDescription):
    """Boiler-device binary sensor description.

    `endpoint` selects which coordinator's data dict feeds `is_on_fn`.
    """

    endpoint: str
    is_on_fn: Callable[[dict[str, Any]], bool | None]


def _summer_off(d: dict[str, Any]) -> bool | None:
    servicing = _as_int(d.get("Servicing"))
    if servicing is None:
        return None
    # Servicing & 0xFF0000 — any bit 16..23. Overlaps per-load Calling bits
    # 16..20; the UI shows "Summer Off" in preference to per-load Calling
    # when both apply (firmware ≥ 2.01 quirk). See docs/protocol.md.
    return bool(servicing & 0xFF0000)


def _remote_mode(d: dict[str, Any]) -> bool | None:
    servicing = _as_int(d.get("Servicing"))
    if servicing is None:
        return None
    return servicing == 0xFFFF


def _sicc_online(d: dict[str, Any]) -> bool | None:
    v = _as_int(d.get("SIP_Online"))
    if v is None:
        return None
    return bool(v)


BOILER_BINARY_DESCRIPTIONS: tuple[IBCBoilerBinarySensorDescription, ...] = (
    IBCBoilerBinarySensorDescription(
        key="sicc_online",
        translation_key="sicc_online",
        endpoint=ENDPOINT_SICC,
        device_class=BinarySensorDeviceClass.CONNECTIVITY,
        entity_category=EntityCategory.DIAGNOSTIC,
        is_on_fn=_sicc_online,
    ),
    IBCBoilerBinarySensorDescription(
        key="summer_off",
        translation_key="summer_off",
        endpoint=ENDPOINT_LIVE,
        entity_category=EntityCategory.DIAGNOSTIC,
        is_on_fn=_summer_off,
    ),
    IBCBoilerBinarySensorDescription(
        key="remote_mode",
        translation_key="remote_mode",
        endpoint=ENDPOINT_LIVE,
        entity_category=EntityCategory.DIAGNOSTIC,
        is_on_fn=_remote_mode,
    ),
)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: IBCConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    runtime = entry.runtime_data
    boiler_device = boiler_device_info(entry, runtime)

    entities: list[BinarySensorEntity] = [
        IBCBoilerBinarySensor(
            runtime.coordinators[description.endpoint],
            entry,
            description,
            boiler_device,
        )
        for description in BOILER_BINARY_DESCRIPTIONS
    ]

    live_coord = runtime.coordinators[ENDPOINT_LIVE]
    for load_no, load_type in runtime.enabled_loads:
        load_device = load_device_info(entry, runtime, load_no, load_type)
        for desc in LOAD_BINARY_DESCRIPTIONS:
            entities.append(
                IBCLoadBinarySensor(live_coord, entry, desc, load_device, load_no)
            )

    async_add_entities(entities)


class IBCBoilerBinarySensor(
    CoordinatorEntity[IBCEndpointCoordinator], BinarySensorEntity
):
    """Boiler-level binary sensor backed by a single endpoint coordinator."""

    _attr_has_entity_name = True
    entity_description: IBCBoilerBinarySensorDescription

    def __init__(
        self,
        coordinator: IBCEndpointCoordinator,
        entry: IBCConfigEntry,
        description: IBCBoilerBinarySensorDescription,
        device_info: DeviceInfo,
    ) -> None:
        super().__init__(coordinator)
        self.entity_description = description
        self._attr_unique_id = f"{boiler_unique_id(entry)}_{description.key}"
        self._attr_device_info = device_info

    @property
    def is_on(self) -> bool | None:
        data = self.coordinator.data
        if not isinstance(data, dict):
            return None
        return self.entity_description.is_on_fn(data)


class IBCLoadBinarySensor(
    CoordinatorEntity[IBCEndpointCoordinator], BinarySensorEntity
):
    """Per-load binary sensor backed by the live coordinator (or=19)."""

    _attr_has_entity_name = True
    entity_description: IBCLoadBinarySensorDescription

    def __init__(
        self,
        coordinator: IBCEndpointCoordinator,
        entry: IBCConfigEntry,
        description: IBCLoadBinarySensorDescription,
        device_info: DeviceInfo,
        load_no: int,
    ) -> None:
        super().__init__(coordinator)
        self.entity_description = description
        self._load_no = load_no
        self._attr_unique_id = load_entity_unique_id(entry, load_no, description.key)
        self._attr_device_info = device_info

    @property
    def is_on(self) -> bool | None:
        data = self.coordinator.data
        if not isinstance(data, dict):
            return None
        return self.entity_description.is_on_fn(data, self._load_no)
