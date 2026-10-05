"""Hard block on outbound network traffic for the whole process.

Once enable() runs, any attempt to open an internet connection (or resolve a
hostname) raises NetworkBlocked. Accepting inbound connections on a socket the
process itself bound (the local web server) is unaffected, as are Unix sockets.
"""
from __future__ import annotations

import socket

_enabled = False


class NetworkBlocked(RuntimeError):
    pass


def _deny(*_args, **_kwargs):
    raise NetworkBlocked("Outbound network access is disabled in rit-press-extractor.")


def enable() -> None:
    global _enabled
    if _enabled:
        return
    real_connect = socket.socket.connect
    real_connect_ex = socket.socket.connect_ex

    def connect(self, address):
        if self.family == socket.AF_UNIX:
            return real_connect(self, address)
        _deny()

    def connect_ex(self, address):
        if self.family == socket.AF_UNIX:
            return real_connect_ex(self, address)
        _deny()

    def sendto(self, *args):
        if self.family == socket.AF_UNIX:
            return _real_sendto(self, *args)
        _deny()

    _real_sendto = socket.socket.sendto
    socket.socket.connect = connect
    socket.socket.connect_ex = connect_ex
    socket.socket.sendto = sendto
    socket.create_connection = _deny
    socket.getaddrinfo = _deny
    socket.gethostbyname = _deny
    socket.gethostbyname_ex = _deny
    _enabled = True


def is_enabled() -> bool:
    return _enabled
