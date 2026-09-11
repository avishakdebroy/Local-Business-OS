"""Finding the address the phone should open."""

from __future__ import annotations

import socket

LOOPBACK = {"127.0.0.1", "::1", "localhost"}


def lan_address() -> str | None:
    """This machine's address on the local network.

    Opens a UDP socket toward a public address to discover which interface the
    OS would route through. UDP 'connect' sends no packets, so this works with
    the internet unplugged — which is the normal state in the shop.
    """
    probe = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        probe.connect(("8.8.8.8", 80))
        address = probe.getsockname()[0]
    except OSError:
        return None
    finally:
        probe.close()
    return None if address.startswith("127.") else address


def is_loopback(host: str | None) -> bool:
    return (host or "") in LOOPBACK


def phone_url(port: int, path: str = "/phone") -> str | None:
    address = lan_address()
    return f"http://{address}:{port}{path}" if address else None
