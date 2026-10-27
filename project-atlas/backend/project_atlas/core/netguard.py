"""Process-level outbound network guard for offline mode.

When installed, every outbound socket connection from this Python process is
checked. Connections to loopback (and, optionally, private LAN) addresses are
allowed; anything else is blocked with ``OfflineViolation`` and recorded so the
offline verification report can show attempted external connections.

This guards only this process. It does not replace an OS firewall or a
physical air gap; see docs/offline-operation.md.
"""

from __future__ import annotations

import ipaddress
import socket
import threading
from collections import deque
from datetime import datetime, timezone

_original_connect = socket.socket.connect
_original_connect_ex = socket.socket.connect_ex
_original_getaddrinfo = socket.getaddrinfo


class OfflineViolation(ConnectionRefusedError):
    pass


class NetworkGuard:
    def __init__(self) -> None:
        self.installed = False
        self.allow_private = True
        self.attempts: deque[dict] = deque(maxlen=200)
        self.blocked_count = 0
        self._lock = threading.Lock()

    def _allowed_host(self, host: str) -> bool:
        if host in {"localhost", "localhost.localdomain"}:
            return True
        try:
            ip = ipaddress.ip_address(host.split("%")[0])
        except ValueError:
            return False  # unresolved hostname: deny (resolution itself is guarded below)
        if ip.is_loopback:
            return True
        from project_atlas.core.config import is_lan_address

        return self.allow_private and is_lan_address(ip)

    def _record(self, kind: str, target: str) -> None:
        with self._lock:
            self.blocked_count += 1
            self.attempts.append({"at": datetime.now(timezone.utc).isoformat(), "kind": kind, "target": target})

    def check_address(self, family: int, address) -> None:
        if family == getattr(socket, "AF_UNIX", -1):
            return
        if isinstance(address, tuple) and address:
            host = str(address[0])
            if not self._allowed_host(host):
                self._record("connect", f"{host}:{address[1] if len(address) > 1 else ''}")
                raise OfflineViolation(f"Project Atlas offline mode blocked outbound connection to {host}")

    def install(self, allow_private: bool = True) -> None:
        self.allow_private = allow_private
        if self.installed:
            return
        guard = self

        def connect(sock, address):
            guard.check_address(sock.family, address)
            return _original_connect(sock, address)

        def connect_ex(sock, address):
            guard.check_address(sock.family, address)
            return _original_connect_ex(sock, address)

        def getaddrinfo(host, *args, **kwargs):
            h = host.decode() if isinstance(host, bytes) else host
            if h is not None and not guard._allowed_host(str(h)):
                # Allow resolution only of literal IPs / localhost; DNS lookups leak intent.
                try:
                    ipaddress.ip_address(str(h))
                except ValueError:
                    guard._record("dns", str(h))
                    raise OfflineViolation(f"Project Atlas offline mode blocked DNS lookup for {h}")
            return _original_getaddrinfo(host, *args, **kwargs)

        socket.socket.connect = connect  # type: ignore[method-assign]
        socket.socket.connect_ex = connect_ex  # type: ignore[method-assign]
        socket.getaddrinfo = getaddrinfo  # type: ignore[assignment]
        self.installed = True

    def uninstall(self) -> None:
        socket.socket.connect = _original_connect  # type: ignore[method-assign]
        socket.socket.connect_ex = _original_connect_ex  # type: ignore[method-assign]
        socket.getaddrinfo = _original_getaddrinfo  # type: ignore[assignment]
        self.installed = False

    def probe(self) -> str:
        """Attempt a real outbound connection to TEST-NET-1; it must be blocked. Not counted as a violation."""
        if not self.installed:
            return "guard not installed"
        sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        sock.settimeout(1)
        with self._lock:
            before = self.blocked_count
        try:
            sock.connect(("192.0.2.1", 443))
            return "connected (unexpected)"
        except OfflineViolation as exc:
            with self._lock:
                self.blocked_count = before
                if self.attempts:
                    self.attempts.pop()
            return f"blocked: {exc}"
        except OSError as exc:
            return f"not blocked by guard: {exc}"
        finally:
            sock.close()

    def report(self) -> dict:
        with self._lock:
            return {"installed": self.installed, "allow_private": self.allow_private,
                    "blocked_count": self.blocked_count, "recent_attempts": list(self.attempts)[-20:]}


guard = NetworkGuard()
