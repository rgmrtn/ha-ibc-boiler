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
| 6 | Lifetime counters (`PowerOnHrs`, `BurnerOnHrs`, `Starts`, `Cycles`, `Errors`, ...) | — |
| 7 | Error/event log entry (`log_no`, `Time`, `Date`, `MinErr`, `MajErr`, `FanRPM`, `InletTemp`, ...) | `object_index` 1..35 |
| 11 | Device info — `model`, `fwversion`, `fwdate`, `imperial`, `model_num`, `designT`, `boiler_id`, `sicc_module` | — |
| 13 | Per-load type + emitter (Load1Type..Load5Type, SB1Enable..SB4Enable, Occupied, Imperial) | — |
| 15 | Combustion/installation config (Altitude, Barometric, VarSpeedMin/Max, VentType) | — |
| 16 | Per-load configuration (LoadType, SupplySetPoint, MaxSupplyT, ...) | `object_index` = load |
| 17 | Master/cascade config (MasterBoiler, BoilerID, StagingDelay, ...) | — |
| **19** | **Live status — primary live-data endpoint.** `Status`, `Status_Enum`, `Warnings`, `Errors`, `ErrorCode`, `MBH`, `SupplyT`, `ReturnT`, `TargetT`, `StackT`, `AirT`, `IndoorT`, `OutdoorT`, `SecondaryT`, `TankT`, `InletPressure`, `OutletPressure`, `DeltaPressure`, `CombiMode`, `Cycles`, `MajorError`, `MinorError`, `SystemError`, `CombiError`, `WarnFlags`, `Pumps`, `IsActiveMaster`, `OpStatus` | — |
| 20 | Combustion/fan detail (InletP, OutletP, FanSpeed, FanDuty, FanTarget, Firing, PID gains, ...) | — |
| 21 | Burner test parameters | — |
| 24 | Date/time/timezone | — |
| 27 | Active load + secondary temperature set | — |
| 32 | Per-zone runtime (Load, Type, HeatOut, SupplyT, ReturnT, Temperature1..6) | `load_no` 1..5 |
| 34 | Network/identity — `mac`, `ipaddr`, `ipmask`, `ipgate`, `ipdns`, `site_name`, `boiler_id`, `network_id`, `bacnet_id`, `portal_status` | — |
| 44 | Flame/SIP/FCP diagnostics (SIP_FlameCurrent, FCP_dcV, FCP_mA, FCP_acV, FCP_Power, ...) | — |

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
| `or32_load01.json` | `Temperature5: 307` mirrors the or=16 setpoint, confirming the encoding is consistent across objects. |

Fresh samples for other object_request codes can be captured at any time —
the boiler exposes the CGI without auth, so a single `curl` or `Invoke-WebRequest`
against `http://<boiler-ip>/cgi-bin/bc2-cgi?json=...` is enough.
