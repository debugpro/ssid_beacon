# Six visible Wi-Fi SSIDs

`six-ssid-beacons.py` broadcasts six experimental SSIDs from one Linux Wi-Fi adapter in monitor mode. It sends 802.11 Beacon frames and rate-limited Probe Responses on channel 6. The names are hard-coded in `NAMES` and each has a distinct locally administered BSSID.

**These are visible-only networks.** The script does not implement authentication, association, DHCP, or internet access. Devices can see the names but cannot connect to them.

## Requirements

- Linux, Python 3.10 or newer, root access, and a Wi-Fi adapter/driver that supports monitor-mode frame injection.
- An authorized test radio and a channel permitted in your region. The tested setup used an RTL8188EUS USB adapter passed through to Ubuntu 22.04, with a separately built `8188eu` driver.
- The adapter must already be tuned to channel 6; the Python script does not configure the radio.

## Run

Identify the interface with `iw dev`. Switching an interface to monitor mode disconnects any existing Wi-Fi connection on it. On a dedicated test adapter:

```bash
IFACE=wlx60ee5c24ce02  # replace with your own interface name
sudo ip link set "$IFACE" down
sudo iw dev "$IFACE" set type monitor
sudo ip link set "$IFACE" up
sudo iw dev "$IFACE" set channel 6
iw dev "$IFACE" info
sudo python3 -u six-ssid-beacons.py "$IFACE"
```

The interface shown by `iw dev` must say `type monitor`. Stop the foreground process with Ctrl-C. Do not start another copy if one is already transmitting on the same interface.

To return a dedicated adapter to managed mode after stopping the script:

```bash
sudo ip link set "$IFACE" down
sudo iw dev "$IFACE" set type managed
sudo ip link set "$IFACE" up
```

## Notes

All six names share one radio and one channel. Visibility depends on the adapter, driver, receiver scan timing, and interference; there is no guarantee that every device will display every name on every scan. The script answers valid broadcast or matching directed Probe Requests from scanning clients, caps responses at 30 groups per second with a burst of six groups, and does not log client addresses. It does not change transmit power or bypass regulatory restrictions.
