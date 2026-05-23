Home Assistant integration for IBC Technologies condensing boilers built on the **V-10 control platform** (CX, SL, HC, DC, VFC series). Polls the boiler's local `bc2-cgi` JSON endpoint over HTTP — no cloud, no auth.

**Read-only.** Exposes temperatures, inlet/outlet/delta pressure, power output (MBH), cycles, status, and error code as sensors. The boiler's model, firmware, and MAC are read from the controller, so the device card reports what you actually have and survives a DHCP IP change.

Configure via **Settings → Devices & Services → Add Integration → IBC Boiler**. You'll need the boiler's IP or hostname; scan interval defaults to 30 s.

Independent project — not affiliated with or endorsed by IBC Technologies. Provided "as is" under the MIT license with no warranty; use at your own risk.
