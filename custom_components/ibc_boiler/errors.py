"""V-10 error/event log decoder.

Translates the bit-mask fields in an `object_request: 7` log entry
(`MajErr`, `MinErr`, `SysErr`, `CombiErr`, `SIM_Status`) into the same
human-readable text the boiler's own web UI shows. Tables and logic are
ported 1:1 from the controller's `/custom/js/error.js`
(`getErrorString()` and its associated `*ERRBITDISPLAYMASK` / `*ERRLIST`
arrays). Keep this file in sync if the boiler firmware revises those
tables.
"""

from __future__ import annotations

from typing import Any

# Bit-mask lookup tables, copied verbatim from error.js.
_HARD_ERR_MASKS: tuple[int, ...] = (0x01, 0x10, 0x20, 0x02, 0x04, 0x08, 0x40)
_HARD_ERR_TEXT: tuple[str, ...] = (
    "Ignition Trials Exceeded",
    "Roll Out Switch",
    "Low Water Cutoff",
    "Module High Current",
    "Sec/Indoor Sensor",
    "Low Water Cutoff",
)

_SYS_ERR_MASKS: tuple[int, ...] = (0x01, 0x02, 0x04, 0x08, 0x10, 0x20, 0x40, 0x80)
_SYS_ERR_TEXT: tuple[str, ...] = (
    "CANbus",
    "CGI Task",
    "I2C Bus 0",
    "I2C Bus 1",
    "BACnet Task",
    "GPIO Expander",
    "LCD Module/Bus",
    "FRAM Module",
)

_SOFT1_MASKS: tuple[int, ...] = (0x0001, 0x0004, 0x0008, 0x0010, 0x0020, 0x0040, 0x0080)
_SOFT1_TEXT: tuple[str, ...] = (
    "Low RPM/Air Flow",
    "Low RPM/Air Flow",
    "No/Low Water Flow",
    "Water High Limit",
    "Vent High Limit",
    "Interlock 1 Open",
    "Interlock 2 Open",
)
_SOFT1_G3_TEXT: tuple[str, ...] = (
    "Flame Sig/Vent Blocked",
    "Low RPM/Air Flow",
    "No/Low Water Flow",
    "Water High Limit",
    "Vent High Limit",
    "Interlock 1 Open",
    "Interlock 2 Open",
)

_SOFT2_MASKS: tuple[int, ...] = (
    0x0100, 0x0200, 0x0400, 0x0800, 0x2000, 0x4000, 0x8000, 0x1000,
)
_SOFT2_TEXT: tuple[str, ...] = (
    "Inlet Pressure Sensor",
    "Outlet Pressure Sensor",
    "No/Low Water Flow",
    "Ignition Module",
    "See Error Log/SIM",
    "Low Water Pressure",
    "Max deltaT Exceeded",
    "Reversed Flow",
)
_SOFT2_G3_TEXT: tuple[str, ...] = (
    "Inlet Pressure Sensor",
    "Fan Pressure",
    "No/Low Water Flow",
    "Low Module Current",
    "See Error Log/SIM",
    "Low Water Pressure",
    "Max deltaT Exceeded",
    "Reversed Flow",
)

_CBI_TEXT: tuple[str, ...] = (
    "No CBI",
    "Diverter Not Detect",
    "No Inlet Temp. Sensor",
    "No Outlet Temp. Sensor",
)

_SIM_MASKS: tuple[int, ...] = (
    0x00000001, 0x00000002, 0x00000004, 0x00000008, 0x00000010, 0x00000020,
    0x00000080, 0x00000040, 0x00000100, 0x00000200, 0x00000400, 0x00000800,
    0x00001000, 0x00002000, 0x00004000, 0x00008000, 0x00010000, 0x00040000,
    0x00080000, 0x00100000, 0x20000000, 0x40000000, 0x80000000,
)
_SIM_TEXT: tuple[str, ...] = (
    "SIM No Spark", "SIM No Flame", "SIM Max Trials", "SIM Low Water",
    "SIM Low Flow", "SIM Outlet Over T", "SIM Outlet Sensor",
    "SIM Stack Over T", "SIM Stack Sensor", "SIM No Flame Drive",
    "SIM No Ign Supply", "SIM No 170V", "SIM No 3.3V", "Gas V Voltage",
    "SIM Gas V Current", "SIM ATD Fault", "SIM No 60Hz Sync",
    "SIM No FCP Comm", "SIM Fail Safe Mode", "SIM No Boiler Comm.",
    "SIM Burner On Call", "SIM Gas Valve Open", "SIM Flame Detected",
)

# model_num values for combi boilers (from ibc-cmn.js: CX_199 = 23, CX_150 = 24).
_COMBI_MODEL_NUMS: frozenset[int] = frozenset({23, 24})

_EMPTY_SLOT_DATE = "00/00/1900"


def _is_sim_model(model: str | None) -> bool:
    """G3/CX/EX/VX families use the alternate SOFT1/SOFT2 text."""
    if not model:
        return False
    return any(token in model for token in ("G3", "CX", "EX", "VX"))


def _is_large_model(model: str | None) -> bool:
    if not model:
        return False
    return ("70-700" in model) or ("85-850" in model)


def _is_combi(model_num: int | None) -> bool:
    return model_num is not None and model_num in _COMBI_MODEL_NUMS


def _as_int(value: Any) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return 0


def is_empty_slot(entry: dict[str, Any] | None) -> bool:
    """True if this log slot is unused (no event ever recorded).

    The boiler returns `Date: "00/00/1900"` for slots above the actual log
    depth. The web UI silently skips these.
    """
    if not entry:
        return True
    return str(entry.get("Date")) == _EMPTY_SLOT_DATE


def decode_error_entry(
    entry: dict[str, Any],
    *,
    model: str | None = None,
    model_num: int | None = None,
) -> str:
    """Return a single, human-readable summary of an or=7 log entry.

    Joins multiple simultaneous faults with `; ` so the result fits on one
    sensor-state line (HA state max 255 chars; messages are short).
    Returns `"None"` (matching the web UI) when no bits are set.
    """
    min_err = _as_int(entry.get("MinErr"))
    maj_err = _as_int(entry.get("MajErr"))
    sys_err = _as_int(entry.get("SysErr"))
    cbi_err = _as_int(entry.get("CombiErr"))
    sim_status = abs(_as_int(entry.get("SIM_Status")))

    is_sim = _is_sim_model(model)
    is_large = _is_large_model(model)
    is_combi = _is_combi(model_num)

    parts: list[str] = []

    # error.js reinterprets a couple of bits: MinErr BIT4/BIT5 escalate
    # to hard errors, MajErr BIT2 downgrades to soft.
    soft_to_hard = 0
    hard_to_soft = 0
    if min_err & 0x10:  # BIT4
        soft_to_hard |= 0x20  # BIT5
    if min_err & 0x20:  # BIT5
        soft_to_hard |= 0x10  # BIT4
    if maj_err & 0x04:  # BIT2
        hard_to_soft = 0x04
    min_err &= ~(0x10 | 0x20)
    maj_err &= ~0x04

    # Minor (soft) errors.
    if min_err or hard_to_soft:
        soft1 = _SOFT1_G3_TEXT if is_sim else _SOFT1_TEXT
        for i, mask in enumerate(_SOFT1_MASKS):
            if min_err & mask:
                parts.append(soft1[i])
        if hard_to_soft:
            parts.append("Temp. Probe Error" if is_sim else "Sec/Indoor Sensor")
        soft2 = _SOFT2_G3_TEXT if is_sim else _SOFT2_TEXT
        for i, mask in enumerate(_SOFT2_MASKS):
            if min_err & mask:
                parts.append(soft2[i])

    # Major (hard) errors.
    if maj_err or soft_to_hard:
        for i, mask in enumerate(_HARD_ERR_MASKS):
            if not (maj_err & mask):
                continue
            text: str | None = None
            # Combi BIT6 override — substitute CBI sub-code.
            if is_combi and mask == 0x40:
                if cbi_err & 0x01:
                    text = _CBI_TEXT[0]
                elif cbi_err & 0x02:
                    text = _CBI_TEXT[1]
                elif cbi_err & 0x04:
                    text = _CBI_TEXT[2]
                elif cbi_err & 0x08:
                    text = _CBI_TEXT[3]
                else:
                    text = _CBI_TEXT[0]
            elif is_large and mask == 0x04:
                text = "High/Low Gas Pressure"
            elif is_sim and mask == 0x20:
                text = "Vent High Pressure"
            elif is_sim and mask == 0x04:
                text = "Temperature Probe Error"
            elif i < len(_HARD_ERR_TEXT):
                text = _HARD_ERR_TEXT[i]
            if text:
                parts.append(text)
        if soft_to_hard & 0x10:
            parts.append("Vent High Limit")
        if soft_to_hard & 0x20:
            parts.append("Water High Limit")

    # System errors.
    if sys_err:
        for i, mask in enumerate(_SYS_ERR_MASKS):
            if sys_err & mask:
                parts.append(_SYS_ERR_TEXT[i])

    # SIM module statuses — only relevant on G3/SIM-equipped boilers.
    if is_sim and sim_status:
        for i, mask in enumerate(_SIM_MASKS):
            if sim_status & mask:
                parts.append(_SIM_TEXT[i])

    return "; ".join(parts) if parts else "None"
