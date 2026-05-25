# IBC V-10 `bc2-cgi` JSON protocol

> Documented from passive observation of the boiler's own browser-based web UI:
> the HTTP calls the UI issues, the JSON the controller returns to those calls,
> and the JavaScript the controller serves to its own browser. No firmware was
> inspected, no authentication was bypassed, and no aggressive probing was
> performed. The CGI endpoint is open on the LAN by design — it's the same
> endpoint the boiler's own UI uses on every page load. This document exists
> so that Home Assistant users with an IBC boiler can read their own equipment
> without depending on a cloud service.

## Endpoint

```
GET http://<boiler-ip>/cgi-bin/bc2-cgi?json=<url-encoded-compact-json>
```

- Plain HTTP on the LAN, no TLS.
- Content-Type of the response is `text/html` even though the body is JSON.
- No authentication on the CGI itself. The PHP front end at `/index.php` gates
  the UI; the underlying CGI is open from any LAN client.

## Request format

```json
{ "object_no": 100, "object_request": <int>, "boiler_no": 0 }
```

Optional fields, depending on the object:
- `object_index` — selects one element of a numbered collection.
- `load_no` — selects one zone/load (1..5 on CX-class boilers).

`object_no` is always `100` and `boiler_no` is always `0` for a single-boiler
setup. The controller responds to a malformed request (e.g. empty `{}`) with
the error envelope `{ "rbid": 0, "object_no": 201, "fail_code": -1, "operation": -2147483648 }`.

## Object_request codes

| code | content | needs index/load |
|---:|---|---|
| 6 | Lifetime counters (`PowerOnHrs`, `BurnerOnHrs`, `Load1OnTime`..`Load5OnTime`, `RemoteOnTime`, `Starts`, `Trials`, `Errors`, `Warnings`, `LogEntries`, `Cycles`, `BiasCount`). Counters tick on hour boundaries (`PowerOnHrs`/`BurnerOnHrs`/`LoadXOnTime`) or per discrete event — polling faster than ~5 min is wasteful. | — |
| 7 | Error/event log entry (`log_no`, `Date`, `Time`, `MinErr`, `MajErr`, `SysErr`, `CombiErr`, `SIM_Status`, `FanRPM`, `InletTemp`, `OutletTemp`, `BoardTemp`, `InletPressure`, `Altitude`, ...) | `object_index` 1..35 |
| 11 | Device info — `model`, `fwversion`, `fwdate`, `imperial`, `model_num`, `designT`, `boiler_id`, `sicc_module` | — |
| 13 | Per-load type + emitter (Load1Type..Load5Type, SB1Enable..SB4Enable, Occupied, Imperial). `LoadXType` values map to friendly names via `LoadNameFromNum()` in `/custom/js/ibc-cmn.js`: 0=Off, 1=DHW, 2=Reset Heating, 3=Set Point, 4=External Control, 5=Manual Control, 6=Zone Of. Value 7 ("On-Demand DHW") appears on Load 5 of combi boilers (`model_num` 23/24) and is labelled directly by the UI rather than through `LoadNameFromNum`. | — |
| 15 | Combustion/installation config (Altitude, Barometric, VarSpeedMin/Max, VentType) | — |
| 16 | Per-load configuration. **Response shape depends on `LoadType`.** `LoadType: 0` (Off) returns a minimal `{load_no, LoadType, OptOutType}` payload (see `or16_idx02.json`). `LoadType: 3` (Set Point) returns the full heating-zone schema with `SupplySetPoint`, `MaxSupplyT`, `SupplyDiffT`, `SummerOff`, `PumpPurgeTime`, `ValveFullSwing`, `Priority`, `WaterTFrom`, `MixingTFrom`, `RampTime`, `PumpOn`, `BurnerOnFrom`, `TankT`, `TankDiffT`, `TankTFrom`. `LoadType: 7` (combi/On-Demand DHW) returns `{Active, OutputTarget, MaxSupplyT, MinSupplyT, FastHeatMode, lowDiffTemp, highDiffTemp, pGain, iGain, dGain, fffGain, minDelta}`. **Reads use `object_index` for the load selector; writes use `load_no` (different parameter name).** | `object_index` = load (read) / `load_no` (write) |
| 17 | Master/cascade config (MasterBoiler, BoilerID, StagingDelay, ...) | — |
| **19** | **Live status — primary live-data endpoint.** `Status`, `Status_Enum`, `Warnings`, `Errors`, `ErrorCode`, `MBH`, `SupplyT`, `ReturnT`, `TargetT`, `StackT`, `AirT`, `IndoorT`, `OutdoorT`, `SecondaryT`, `TankT`, `InletPressure`, `OutletPressure`, `DeltaPressure`, `CombiMode`, `Cycles`, `MajorError`, `MinorError`, `SystemError`, `CombiError`, `WarnFlags`, `Pumps`, `Servicing`, `IsActiveMaster`, `OpStatus`. See "Servicing bitfield" below for per-load pump/calling decoding. The `Pumps` integer is exposed but **not used by the web UI** — prefer `Servicing` for per-load status. | — |
| 20 | Combustion/fan detail (InletP, OutletP, FanSpeed, FanDuty, FanTarget, Firing, PID gains, ...) | — |
| 21 | Burner test parameters | — |
| 24 | Date/time/timezone | — |
| 27 | Active load + secondary temperature set | — |
| 32 | Per-zone runtime — `Load` (0-indexed, equals `load_no - 1` in the response), `Type` (same enum as or=13's LoadXType), `HeatOut` (MBH), `SupplyT`, `ReturnT`, `BoilerMax`, `BoilerDiff`, `Cycles`, `Priority`, `Temperature1..6` (per-LoadType semantics — left undocumented in this integration). The CGI selects the load via the `load_no` request parameter (1..5). See `or32_load01.json` and `or32_load05.json`. | `load_no` 1..5 |
| 34 | Network/identity — `mac`, `ipaddr`, `ipmask`, `ipgate`, `ipdns`, `site_name`, `boiler_id`, `network_id`, `bacnet_id`, `portal_status` | — |
| 44 | Flame/SIP/FCP diagnostics (`SIP_FlameCurrent`, `SIP_FlameOut`, `SIP_Online`, `SIP_Info`, `SIP_Checksum`, `SIP_Status`, `FCP_dcV`, `FCP_mA`, `FCP_PmA`, `FCP_acV`, `FCP_IDSense`, `FCP_Power`, `FCP_Info`, `FCP_Checksum`, `FCP_Status`). `SIP_FlameCurrent` is displayed by the boiler's own `error.js` as `parseFloat(SIM_Flame / 249).toFixed(2)` µA — the same divisor (249) applies to `SIP_FlameCurrent` here. `SIP_Online` is a 0/1 flag. | — |

## Response envelope

Every successful response is a flat (occasionally one-level-nested) JSON object
that includes:

```json
{ "rbid": 0, "dump": <object_request>, "object_no": <object_no>, ...payload }
```

- `rbid` — echo of a request body id; always `0` from the V-10 web UI.
- `dump` — equals the `object_request` value, so callers can verify they got
  the dump they asked for.
- `fail_code` — present only on error responses; non-zero / `-1` means the
  controller rejected the request.

## Units

- `imperial: 31` in `object_request: 11` indicates the **user's preferred
  display unit** in the boiler web UI is imperial. It does **not** affect
  what the CGI returns over JSON — every integration must do its own unit
  conversion from the raw values below.
- **Temperatures are in quarter-degrees Celsius** in every object that
  reports a temperature (or=19 `SupplyT`/`ReturnT`/`TargetT`/`StackT`/...,
  or=16 `SupplySetPoint`/`TankT`/..., or=32 `Temperature1..6`, or=27
  `InletTemp`/`OutletTemp`/..., etc.). To convert: `°C = raw / 4`,
  `°F = raw × 0.45 + 32`. Verified against the boiler web UI's own
  `displayTemp()` JS, which contains the explicit comment:
  `// All temperatures to and from the boiler are in °C * 4 (eg. 80 = 20°C)`.
  Several fields in or=19 are *visually* in a plausible °F range
  (`SupplyT: 192` → 192 °F looks reasonable for a boiler) but this is a
  coincidence — they are actually 48 °C / 118 °F. Always divide by 4.
- **Pressures** in or=19 (`InletPressure`, `OutletPressure`, `DeltaPressure`)
  are decimal psi already (`16.6` = 16.6 psi). No conversion needed.
- `object_request: 20` returns the same pressure values as **integer
  tenths** (`InletP: 166` = 16.6 psi). Stick to or=19 unless you need
  fan/PID detail. Temperatures in or=20 are still quarter-°C.
- `object_request: 7` also reports pressures as **integer tenths** of
  psi (`InletPressure: 170` = 17.0 psi). Confirmed in `error.js`:
  `displayPressure(respobj.InletPressure / 10)`. Temperatures in or=7
  are still quarter-°C.
- `object_request: 19`'s `TargetT` is the controller's current water target
  (driven by demand, outdoor reset, mode). When DHW is the active load on a
  combi-capable boiler, the home page's "On-Demand DHW Target" displays
  this same `TargetT` value. The HA integration surfaces it as "Internal
  Target".
- **Power output `MBH`** = thousand BTU/hr, reported as a whole integer.
  No scaling. (The web UI's `displayHeatOutput()` only converts to kW
  when the user picks metric.)

## Sentinels

- **`-32766`** in any temperature field means "sensor not connected". The HA
  integration converts this to `None`/unknown rather than surfacing the
  sentinel value.
- In `object_request: 7` log entries, **`Date: "00/00/1900"`** marks an
  empty (never-used) slot above the actual log depth. The web UI silently
  skips these and the HA integration does the same.

## Servicing bitfield (or=19)

The `Servicing` integer in or=19 packs per-load status flags. Ported
from `custom/js/index.js:428-449`:

```
bit (load_no - 1)        Servicing flag (load is in service mode)
bit (load_no - 1) + 8    Circulating (load's pump is running)
bit (load_no - 1) + 16   Calling (load is calling for heat)
```

Loads are numbered 1..5 on current firmware (≥ 2.01), so the active
bit ranges are 0..4 (Servicing), 8..12 (Circulating), 16..20 (Calling).
The legacy `js/index.js` uses a narrower 0..3 / 4..7 / 8..11 layout
for 4-load older boards.

Special whole-field values the UI interprets specially:
- `Servicing == 0xFFFF` → "Remote" mode.
- `Servicing & 0xFF0000` (any bit 16..23 set) → "Summer Off". This
  check overlaps the per-load Calling bits in current firmware — the
  UI shows "Summer Off" in preference to per-load Calling when both
  apply.

## Error-log decoding (or=7)

Each `object_request: 7` slot carries a set of bit-mask fields that the
boiler's own UI converts to readable text via `getErrorString()` in
`/custom/js/error.js`:

- `MajErr` — hard errors (mask table `HARDERRBITDISPLAYMASK` → `HARDERRLIST`).
- `MinErr` — soft errors (mask tables `SOFT1ERRBITDISPLAYMASK` /
  `SOFT2ERRBITDISPLAYMASK` → `SOFT1ERRLIST` / `SOFT2ERRLIST`, with G3
  variants for SIM-equipped boilers).
- `SysErr` — system-bus faults (`SYSERRBITDISPLAYMASK` → `SYSERRLIST`).
- `CombiErr` — on combi boilers, when `MajErr` bit 6 is set, the
  CBI sub-code in `CombiErr` replaces the (otherwise out-of-range) hard
  text with one of `CBIERRLIST`.
- `SIM_Status` — additional 32-bit SIM-module status flags decoded via
  `SIMSTATUSBITDISPLAYMASK` / `SIMSTATUSLIST`, only relevant on G3/SIM
  models.

Model identification (for the combi / G3 / large-boiler overrides) uses
the `model` string and `model_num` from `object_request: 11`. Combi
models are `model_num` 23 (CX 199) and 24 (CX 150).

`log_no` echoes the requested `object_index`. Entries are ordered most-
recent-first: `object_index=1` is the latest event. The integration
polls only index 1 and fires a `ibc_boiler_error_logged` HA event when
its identity tuple (log_no + date + time + raw bits) changes.

## Sample payloads

Captured live payloads from a CX 199 (firmware `2.01.7`, build `Dec 16 2024`)
are checked in under `docs/samples/` (MAC and IP sanitized). The set is
deliberately small — each file is here to back a specific claim in this
document:

| file | grounds |
|---|---|
| `or11.json` | Device info fields read at setup (`model`, `fwversion`, `fwdate`). |
| `or19.json` | Live-data shape; `TargetT: 207` demonstrates the quarter-°C encoding (207 / 4 = 51.75 °C = 125 °F). |
| `or34.json` | Network identity used for the HA device's MAC connection. |
| `or16_idx01.json` | `SupplySetPoint: 307` confirms quarter-°C scaling on per-load config (307 / 4 = 76.75 °C = 170 °F). |
| `or16_idx05.json` | LoadType=7 (On-Demand DHW / combi) schema — different field set from LoadType=3 (e.g. `OutputTarget`, `MinSupplyT`, PID gains), demonstrating that or=16's response shape depends on the load's type. |
| `or32_load01.json` | `Temperature5: 307` mirrors the or=16 setpoint, confirming the encoding is consistent across objects. |
| `or07_idx01.json` | Error-log entry shape — `MajErr: 64` + `CombiErr: 1` on a combi boiler decodes to "No CBI"; demonstrates the `12/30/1999` date that appears when the RTC hadn't been set at the time of the event. |
| `or16_idx02.json` | Per-load config for a disabled load (`LoadType: 0`) — minimal `{load_no, LoadType, OptOutType}` shape, contrasts with the full schemas in `or16_idx01.json` (Set Point) and similar combi captures. |
| `or13.json` | Per-load type enumeration. Demonstrates the `LoadXType` numbering (here Load 1 = Set Point (3), Load 5 = On-Demand DHW (7), Loads 2..4 = Off (0)). |
| `or32_load01.json` / `or32_load05.json` | Per-load runtime, one capture per enabled load. Shows the 0-indexed `Load` field in the response (0 → load_no 1, 4 → load_no 5) and confirms `Type` matches the LoadXType from or=13. |

Fresh samples for other object_request codes can be captured at any time —
the boiler exposes the CGI without auth, so a single `curl` or `Invoke-WebRequest`
against `http://<boiler-ip>/cgi-bin/bc2-cgi?json=...` is enough.
