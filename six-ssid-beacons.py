#!/usr/bin/env python3
"""Transmit six visible-only 802.11 beacon SSIDs on a monitor-mode test radio.

These frames do not implement association, authentication, DHCP, or Internet access.
"""

import signal
import select
import socket
import struct
import sys
import time


NAMES = [f"一起创造牛逼+{i}" for i in range(1, 7)]
CHANNEL = 6
# The advertised beacon interval is measured in 1024-microsecond TUs.
# Keep the actual per-BSSID cadence consistent with that field.
BEACON_INTERVAL_TU = 100
INTERVAL_SECONDS = BEACON_INTERVAL_TU * 1024 / 1_000_000
RADIO_TAP = b"\x00\x00\x08\x00\x00\x00\x00\x00"
WILDCARD_BSSID = b"\xff" * 6
ZERO_BSSID = b"\x00" * 6
PROBE_GROUPS_PER_SECOND = 30
PROBE_GROUP_BURST = 6
RUNNING = True


def stop(_signum, _frame):
    global RUNNING
    RUNNING = False


def management_frame(
    name: str, index: int, sequence: int, subtype: int, destination: bytes
) -> bytes:
    ssid = name.encode("utf-8")
    if len(ssid) > 32:
        raise ValueError("SSID exceeds 32 bytes")
    bssid = bytes((0x02, 0x44, 0x50, 0x49, 0x00, index))
    header = (
        bytes((subtype, 0))
        + b"\x00\x00"  # duration
        + destination
        + bssid  # source
        + bssid  # BSSID
        + struct.pack("<H", (sequence & 0xFFF) << 4)
    )
    fixed = struct.pack(
        "<QHH", int(time.monotonic() * 1_000_000), BEACON_INTERVAL_TU, 0x0001
    )
    elements = (
        bytes((0, len(ssid)))
        + ssid
        + b"\x01\x04\x82\x84\x8b\x96"  # basic 1, 2, 5.5, 11 Mbps
        + bytes((3, 1, CHANNEL))
    )
    return RADIO_TAP + header + fixed + elements


def beacon(name: str, index: int, sequence: int) -> bytes:
    return management_frame(name, index, sequence, 0x80, b"\xff" * 6)


def probe_response(
    name: str, index: int, sequence: int, destination: bytes
) -> bytes:
    return management_frame(name, index, sequence, 0x50, destination)


def bssid(index: int) -> bytes:
    return bytes((0x02, 0x44, 0x50, 0x49, 0x00, index))


def requested_ssid(packet: bytes) -> tuple[bytes, bytes, bytes] | None:
    """Return source, SSID and BSSID from a valid scan request on this radio."""
    if len(packet) < 8:
        return None
    radiotap_length = struct.unpack_from("<H", packet, 2)[0]
    if radiotap_length < 8 or len(packet) < radiotap_length + 24:
        return None
    frame = packet[radiotap_length:]
    if frame[0] != 0x40:
        return None
    destination, source, requested_bssid = frame[4:10], frame[10:16], frame[16:22]
    our_bssids = tuple(bssid(index) for index in range(1, len(NAMES) + 1))
    if source == ZERO_BSSID or source[0] & 1:
        return None
    if destination != WILDCARD_BSSID and destination not in our_bssids:
        return None
    if requested_bssid not in (WILDCARD_BSSID, ZERO_BSSID) and requested_bssid not in our_bssids:
        return None
    elements = frame[24:]
    position = 0
    while position + 2 <= len(elements):
        tag, length = elements[position], elements[position + 1]
        position += 2
        if position + length > len(elements):
            return None
        if tag == 0:
            if length > 32:
                return None
            return source, elements[position : position + length], requested_bssid
        position += length
    return None


def matching_names(ssid: bytes, requested_bssid: bytes) -> list[tuple[int, str]]:
    return [
        (index, name)
        for index, name in enumerate(NAMES, 1)
        if (not ssid or ssid == name.encode("utf-8"))
        and requested_bssid in (WILDCARD_BSSID, ZERO_BSSID, bssid(index))
    ]


def refill_tokens(tokens: float, elapsed: float) -> float:
    return min(PROBE_GROUP_BURST, tokens + max(0.0, elapsed) * PROBE_GROUPS_PER_SECOND)


def main() -> int:
    if len(sys.argv) != 2:
        print("usage: six-ssid-beacons.py MONITOR_INTERFACE", file=sys.stderr)
        return 2
    interface = sys.argv[1]
    signal.signal(signal.SIGTERM, stop)
    signal.signal(signal.SIGINT, stop)
    with socket.socket(socket.AF_PACKET, socket.SOCK_RAW, socket.htons(3)) as radio:
        radio.bind((interface, 0))
        print(f"beacon_injection_started interface={interface} channel={CHANNEL}", flush=True)
        print("probe_response_scope=any_scanning_client", flush=True)
        for name in NAMES:
            print(f"ssid={name} bytes={len(name.encode('utf-8'))}", flush=True)
        sequences = [0] * len(NAMES)
        cycle = 0
        sent = 0
        responses = 0
        limited = 0
        tokens = float(PROBE_GROUP_BURST)
        token_time = time.monotonic()
        spacing = INTERVAL_SECONDS / len(NAMES)
        deadline = time.monotonic()
        while RUNNING:
            for position in range(len(NAMES)):
                if not RUNNING:
                    break
                index = (position + cycle) % len(NAMES) + 1
                name = NAMES[index - 1]
                packet = beacon(name, index, sequences[index - 1])
                radio.send(packet)
                sequences[index - 1] += 1
                sent += 1
                deadline += spacing
                while RUNNING:
                    remaining = deadline - time.monotonic()
                    if remaining <= 0:
                        deadline = max(deadline, time.monotonic())
                        break
                    if not select.select([radio], [], [], remaining)[0]:
                        break
                    request = requested_ssid(radio.recv(4096))
                    if request is None:
                        continue
                    client, ssid, requested_bssid = request
                    targets = matching_names(ssid, requested_bssid)
                    if not targets:
                        continue
                    now = time.monotonic()
                    tokens = refill_tokens(tokens, now - token_time)
                    token_time = now
                    if tokens < 1:
                        limited += 1
                        continue
                    tokens -= 1
                    for response_index, response_name in targets:
                        radio.send(
                            probe_response(
                                response_name,
                                response_index,
                                sequences[response_index - 1],
                                client,
                            )
                        )
                        sequences[response_index - 1] += 1
                        responses += 1
                        # The RTL8188EU has a small management TX buffer pool.
                        time.sleep(0.001)
            cycle += 1
            if cycle % 400 == 0:
                print(
                    f"beacons_submitted={sent} probe_responses_submitted={responses} "
                    f"probe_requests_rate_limited={limited}",
                    flush=True,
                )
    print(
        f"beacon_injection_stopped submitted={sent} probe_responses_submitted={responses}",
        flush=True,
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
