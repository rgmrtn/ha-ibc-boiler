"""DeviceInfo builders for the boiler and its per-load child devices.

Centralized here (instead of repeating in each platform file) so the
identifier scheme stays consistent between sensor.py and binary_sensor.py.
"""

from __future__ import annotations

from typing import Any

from homeassistant.helpers.device_registry import (
    CONNECTION_NETWORK_MAC,
    DeviceInfo,
    format_mac,
)

from .const import (
    CONF_HOST,
    DEFAULT_MODEL,
    DOMAIN,
    LOAD_TYPE_NAMES,
    MANUFACTURER,
)
from .coordinator import IBCConfigEntry, IBCRuntimeData


def _str_or_none(value: Any) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    return text or None


def boiler_unique_id(entry: IBCConfigEntry) -> str:
    """The boiler device's identifier value — also the parent for via_device."""
    return entry.unique_id or entry.entry_id


def boiler_device_info(entry: IBCConfigEntry, runtime: IBCRuntimeData) -> DeviceInfo:
    """DeviceInfo for the top-level boiler device."""
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
        identifiers={(DOMAIN, boiler_unique_id(entry))},
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


def load_device_info(
    entry: IBCConfigEntry,
    runtime: IBCRuntimeData,
    load_no: int,
    load_type: int,
) -> DeviceInfo:
    """DeviceInfo for one per-load child device, linked to the boiler via via_device.

    Identifier scheme: `(DOMAIN, f"{boiler_unique_id}_load_{load_no}")`. Keep
    stable — entity unique_ids derive from this.
    """
    parent = boiler_unique_id(entry)
    network = runtime.network or {}
    site_name = _str_or_none(network.get("site_name")) or entry.title
    friendly = LOAD_TYPE_NAMES.get(load_type, f"Type {load_type}")

    return DeviceInfo(
        identifiers={(DOMAIN, f"{parent}_load_{load_no}")},
        via_device=(DOMAIN, parent),
        manufacturer=MANUFACTURER,
        model=f"V-10 Load (type {load_type} — {friendly})",
        name=f"{site_name} Load {load_no} ({friendly})",
    )


def load_entity_unique_id(entry: IBCConfigEntry, load_no: int, key: str) -> str:
    """Stable unique_id for a per-load entity."""
    return f"{boiler_unique_id(entry)}_load_{load_no}_{key}"
