# ha-ibc-boiler

Home Assistant custom integration for IBC Technologies condensing boilers built on the **V-10 control platform** - including the CX, SL, HC, DC, and VFC series. Developed and tested against the **IBC CX 199** (`ICGFSW1-0199`), but the V-10 controller is the same runtime across the lineup, so any model that exposes the local `bc2-cgi` JSON endpoint should work. The boiler model and firmware version are read from the boiler's response so the device card reports what you actually have.

**v0.1 is read-only.** It polls the boiler over HTTP and surfaces temperatures, outlet pressure, power output, and status as Home Assistant sensors. No setpoints, no control, no climate entity yet.

## What it talks to

```
http://<boiler-ip>/cgi-bin/bc2-cgi?json={}
```

Plain HTTP on the LAN, no auth on the CGI itself. The integration is `local_polling` only - it does not talk to IBC's V10 cloud portal.

## Assumptions

- Boiler is reachable from your HA host (same VLAN, no captive portal).
- The V-10 reports all temperatures internally in quarter-degrees Celsius and pressures in decimal psi, regardless of the imperial/metric preference set in the boiler's web UI. The integration converts temperatures to °C (HA renders °F automatically for imperial users); psi is surfaced as-is.
- MBH (thousand BTU/hr) is shown as the boiler reports it; no conversion to watts.

## Installation

### HACS (recommended)

1. HACS → ⋮ → **Custom repositories** → add `https://github.com/rgmrtn/ha-ibc-boiler`, category **Integration**.
2. Install **IBC Boiler** from HACS.
3. Restart Home Assistant.
4. **Settings → Devices & Services → Add Integration**, search **IBC Boiler**, enter the boiler's hostname or IP.

### Manual

1. Copy `custom_components/ibc_boiler/` into your HA `config/custom_components/` directory.
2. Restart Home Assistant.
3. Add the integration via the UI as above.

## Configuration

Set during the **Add Integration** flow (and editable later via **Configure**):

| Field | Default | Notes |
|---|---|---|
| Host | - | IP or hostname of the boiler. |
| Scan interval | 30 s | Range 10–600 s. The boiler's data doesn't move fast; don't poll harder than you need to. |

## Entities created

One device per boiler. The boiler's `model` and firmware version are read from the V-10 controller and used for the device card; the MAC address (also read from the controller) is used as the stable unique identifier so the integration survives a DHCP-induced IP change.

Sensors:

- Supply Temperature
- Return Temperature
- Internal Target - the controller's current water target, recomputed continuously from demand, outdoor reset, mode. On a combi-capable boiler this is also what the web UI's "On-Demand DHW Target" displays when DHW is the active load.
- Stack Temperature
- Outdoor Temperature
- Indoor Temperature
- Tank Temperature - combi DHW
- Inlet Pressure (psi)
- Outlet Pressure (psi)
- Delta Pressure (psi)
- Power Output (MBH)
- Cycles (diagnostic, total-increasing)
- Status (diagnostic, text)
- Error Code (diagnostic)

Temperatures are reported in °C (the V-10's native unit — see `docs/protocol.md`). Home Assistant converts to °F automatically if your profile is set to imperial. Temperatures from sensors that aren't wired up read as `unknown` rather than the V-10's `-32766` sentinel value.

## Debug logging

Add to `configuration.yaml` while you're testing, then remove:

```yaml
logger:
  default: warning
  logs:
    custom_components.ibc_boiler: debug
```

Restart HA, then watch `home-assistant.log` for `custom_components.ibc_boiler` lines.

## Uninstall

1. **Settings → Devices & Services → IBC Boiler → ⋮ → Delete**.
2. Stop Home Assistant.
3. Remove the `custom_components/ibc_boiler/` folder (or uninstall via HACS).
4. Start Home Assistant.

## Disclaimer

- **Independent project.** Not affiliated with, endorsed by, or supported by IBC Technologies. "IBC", "V-10", and product names like "CX 199" are referenced only to describe what this integration works with, and remain the trademarks of their respective owners.
- **No warranty, no liability.** This software is provided "as is" — see the full disclaimer in [LICENSE](LICENSE). The author accepts no responsibility for damage to your boiler, your heating system, your Home Assistant install, or anything else. Use at your own risk against your own equipment.
- **How the protocol map was produced.** Every endpoint and field documented in `docs/protocol.md` was identified by *observing the HTTP traffic the boiler's own web UI issues to itself* (via standard browser DevTools) and by reading the *JavaScript the boiler serves to its own browser UI*. No firmware was inspected, no authentication was bypassed (the CGI is unauthenticated on the LAN by design — it's the same endpoint the boiler's UI uses on every page load), and nothing was fuzzed or stressed. The integration replays the same calls the web UI already makes, at a slower polling rate.

## License

MIT — see [LICENSE](LICENSE).
