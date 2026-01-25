"""SIP client for Dom.ru Smart Intercom to receive incoming calls."""

from __future__ import annotations

import asyncio
import hashlib
import logging
import secrets
import socket as sync_socket
import uuid
from typing import TYPE_CHECKING, Any, Callable

if TYPE_CHECKING:
    pass

_LOGGER = logging.getLogger(__name__)


class DomruSipClient:
    """SIP client for receiving incoming calls from Dom.ru intercom."""

    def __init__(
        self,
        realm: str,
        username: str,
        password: str,
        local_ip: str | None = None,
        local_port: int = 5060,
        on_call_callback: Callable[[dict[str, Any]], None] | None = None,
    ) -> None:
        """Initialize SIP client."""
        self.realm = realm
        self.username = username
        self.password = password
        self.local_ip = local_ip or self._get_local_ip()
        self.local_port = local_port
        self.on_call_callback = on_call_callback

        self._transport: asyncio.DatagramTransport | None = None
        self._protocol: SipProtocol | None = None
        self._call_id: str | None = None
        self._cseq = 0
        self._expires = 60
        self._register_timer: asyncio.TimerHandle | None = None
        self._auth_failure = 0
        self._last_nonce: str | None = None
        self._running = False

    def _get_local_ip(self) -> str:
        """Get local IP address."""
        try:
            # Create a socket to determine the local IP
            s = sync_socket.socket(sync_socket.AF_INET, sync_socket.SOCK_DGRAM)
            s.connect(("8.8.8.8", 80))
            local_ip = s.getsockname()[0]
            s.close()
            return local_ip
        except Exception as err:
            _LOGGER.error("Failed to get local IP: %s", err)
            return "127.0.0.1"

    @staticmethod
    def _md5(s: str) -> str:
        """Calculate MD5 hash."""
        return hashlib.md5(s.encode()).hexdigest()

    @staticmethod
    def _tag() -> str:
        """Generate random tag."""
        return secrets.token_hex(4)

    def _build_auth(self, realm: str, nonce: str) -> str:
        """Build SIP authorization header."""
        ha1 = self._md5(f"{self.username}:{realm}:{self.password}")
        ha2 = self._md5(f"REGISTER:sip:{self.realm}")
        response = self._md5(f"{ha1}:{nonce}:{ha2}")

        return (
            f'Digest username="{self.username}", realm="{realm}", '
            f'nonce="{nonce}", uri="sip:{self.realm}", response="{response}"'
        )

    def _build_register(self, auth: str | None = None) -> str:
        """Build SIP REGISTER message."""
        expires_value = 0 if self._cseq == 1 else self._expires

        msg = (
            f"REGISTER sip:{self.realm} SIP/2.0\r\n"
            f"Via: SIP/2.0/UDP {self.local_ip}:{self.local_port};branch=z9hG4bK{self._tag()};rport\r\n"
            f"Max-Forwards: 70\r\n"
            f"From: <sip:{self.username}@{self.realm}>;tag={self._tag()}\r\n"
            f"To: <sip:{self.username}@{self.realm}>\r\n"
            f"Call-ID: {self._call_id}\r\n"
            f"CSeq: {self._cseq} REGISTER\r\n"
            f"Contact: <sip:{self.username}@{self.local_ip}:{self.local_port};ob>;reg-id=42;expires={expires_value}\r\n"
            f"Supported: outbound\r\n"
            f"Allow-Events: message-summary\r\n"
            f"Expires: {expires_value}\r\n"
            f"User-Agent: Home Assistant Dom.ru Integration\r\n"
        )

        if auth:
            msg += f"Authorization: {auth}\r\n"

        msg += "Content-Length: 0\r\n\r\n"
        return msg

    def _send(self, message: str) -> None:
        """Send SIP message."""
        if self._transport:
            _LOGGER.debug("Sending SIP message:\n%s", message)
            self._transport.sendto(message.encode(), (self.realm, 5060))

    def _send_register(self, auth: str | None = None) -> None:
        """Send REGISTER request."""
        self._send(self._build_register(auth))

    def _schedule_register(self) -> None:
        """Schedule next REGISTER."""
        if self._register_timer:
            self._register_timer.cancel()

        loop = asyncio.get_event_loop()
        self._register_timer = loop.call_later(
            (self._expires - 5),
            self._do_register,
        )

    def _do_register(self) -> None:
        """Execute scheduled REGISTER."""
        self._cseq += 1
        self._send_register()

    def _unregister(self) -> None:
        """Reset registration state."""
        self._call_id = str(uuid.uuid4())
        self._cseq = 1
        self._expires = 60

        if self._register_timer:
            self._register_timer.cancel()
            self._register_timer = None

        self._auth_failure = 0
        self._last_nonce = None

    async def start(self) -> None:
        """Start SIP client."""
        if self._running:
            return

        _LOGGER.info(
            "Starting SIP client: %s@%s (local: %s:%d)",
            self.username,
            self.realm,
            self.local_ip,
            self.local_port,
        )

        loop = asyncio.get_event_loop()

        self._protocol = SipProtocol(self)
        self._transport, _ = await loop.create_datagram_endpoint(
            lambda: self._protocol,
            local_addr=(self.local_ip, self.local_port),
        )

        self._running = True
        self._unregister()
        self._send_register()

    async def stop(self) -> None:
        """Stop SIP client."""
        if not self._running:
            return

        _LOGGER.info("Stopping SIP client")

        if self._register_timer:
            self._register_timer.cancel()

        if self._transport:
            self._transport.close()

        self._running = False

    def _handle_200_ok(self, message: str) -> None:
        """Handle 200 OK response."""
        if "REGISTER" not in message:
            return

        self._auth_failure = 0
        self._last_nonce = None

        # Extract expires
        import re
        exp_match = re.search(r"Expires:\s*(\d+)", message, re.IGNORECASE)
        if exp_match and int(exp_match.group(1)) > 0:
            self._expires = int(exp_match.group(1))

        if self._cseq == 1:
            # First registration, send again with credentials
            asyncio.get_event_loop().call_later(0.25, self._send_register)
        else:
            # Schedule next registration
            self._schedule_register()

    def _handle_401_unauthorized(self, message: str) -> None:
        """Handle 401 Unauthorized response."""
        import re

        realm_match = re.search(r'realm="([^"]+)"', message, re.IGNORECASE)
        nonce_match = re.search(r'nonce="([^"]+)"', message, re.IGNORECASE)

        if not realm_match or not nonce_match:
            _LOGGER.error("Invalid 401 response, missing realm or nonce")
            return

        realm = realm_match.group(1)
        nonce = nonce_match.group(1)

        if self._last_nonce == nonce:
            self._auth_failure += 1
        else:
            self._auth_failure = 1
            self._last_nonce = nonce

        if self._auth_failure >= 2:
            _LOGGER.error("SIP authentication failed - invalid credentials")
            return

        self._cseq += 1
        auth = self._build_auth(realm, nonce)
        self._send_register(auth)

    def _handle_403_forbidden(self) -> None:
        """Handle 403 Forbidden response."""
        _LOGGER.error("SIP registration forbidden (403)")

    def _handle_invite(self, message: str, addr: tuple[str, int]) -> None:
        """Handle incoming INVITE (call)."""
        _LOGGER.info("Incoming call from %s:%d", addr[0], addr[1])

        # Extract SIP headers
        headers = self._extract_headers(message)

        # Notify about incoming call
        if self.on_call_callback:
            self.on_call_callback({
                "event": "incoming_call",
                "from": headers.get("from"),
                "to": headers.get("to"),
                "call_id": headers.get("call_id"),
            })

        # Send responses: 100 Trying, 180 Ringing, 486 Busy Here
        self._send_invite_responses(message, addr)

    def _extract_headers(self, message: str) -> dict[str, str]:
        """Extract common SIP headers."""
        import re

        def extract_header(name: str, short: str | None = None) -> str | None:
            pattern = f"^({name}"
            if short:
                pattern += f"|{short}"
            pattern += r"):.*$"
            match = re.search(pattern, message, re.MULTILINE | re.IGNORECASE)
            return match.group(0) if match else None

        return {
            "via": extract_header("Via", "v") or "",
            "from": extract_header("From", "f") or "",
            "to": extract_header("To", "t") or "",
            "call_id": extract_header("Call-ID", "i") or "",
            "cseq": extract_header("CSeq") or "",
        }

    def _send_invite_responses(self, message: str, addr: tuple[str, int]) -> None:
        """Send responses to INVITE."""
        headers = self._extract_headers(message)
        to_tag = self._tag()

        trying = (
            f"SIP/2.0 100 Trying\r\n"
            f"{headers['via']}\r\n"
            f"{headers['from']}\r\n"
            f"{headers['to']};tag={to_tag}\r\n"
            f"{headers['call_id']}\r\n"
            f"{headers['cseq']}\r\n"
            f"Content-Length: 0\r\n\r\n"
        )

        ringing = (
            f"SIP/2.0 180 Ringing\r\n"
            f"{headers['via']}\r\n"
            f"{headers['from']}\r\n"
            f"{headers['to']};tag={to_tag}\r\n"
            f"{headers['call_id']}\r\n"
            f"{headers['cseq']}\r\n"
            f"Content-Length: 0\r\n\r\n"
        )

        busy = (
            f"SIP/2.0 486 Busy Here\r\n"
            f"{headers['via']}\r\n"
            f"{headers['from']}\r\n"
            f"{headers['to']};tag={to_tag}\r\n"
            f"{headers['call_id']}\r\n"
            f"{headers['cseq']}\r\n"
            f"Content-Length: 0\r\n\r\n"
        )

        # Send responses with delays
        loop = asyncio.get_event_loop()
        loop.call_later(0.025, lambda: self._transport.sendto(trying.encode(), addr))
        loop.call_later(0.150, lambda: self._transport.sendto(ringing.encode(), addr))
        loop.call_later(25.0, lambda: self._transport.sendto(busy.encode(), addr))

    def _handle_options(self, message: str, addr: tuple[str, int]) -> None:
        """Handle OPTIONS request."""
        headers = self._extract_headers(message)

        ok = (
            f"SIP/2.0 200 OK\r\n"
            f"{headers['via']}\r\n"
            f"{headers['from']}\r\n"
            f"{headers['to']};tag={self._tag()}\r\n"
            f"{headers['call_id']}\r\n"
            f"{headers['cseq']}\r\n"
            f"Allow: INVITE, ACK, CANCEL, OPTIONS, BYE, NOTIFY\r\n"
            f"User-Agent: Home Assistant Dom.ru Integration\r\n"
            f"Content-Length: 0\r\n\r\n"
        )

        if self._transport:
            self._transport.sendto(ok.encode(), addr)

    def _handle_notify(self, message: str, addr: tuple[str, int]) -> None:
        """Handle NOTIFY request."""
        headers = self._extract_headers(message)

        ok = (
            f"SIP/2.0 200 OK\r\n"
            f"{headers['via']}\r\n"
            f"{headers['from']}\r\n"
            f"{headers['to']};tag={self._tag()}\r\n"
            f"{headers['call_id']}\r\n"
            f"{headers['cseq']}\r\n"
            f"User-Agent: Home Assistant Dom.ru Integration\r\n"
            f"Content-Length: 0\r\n\r\n"
        )

        if self._transport:
            self._transport.sendto(ok.encode(), addr)

    def handle_message(self, data: bytes, addr: tuple[str, int]) -> None:
        """Handle incoming SIP message."""
        message = data.decode("utf-8", errors="ignore")
        _LOGGER.debug("Received SIP message from %s:%d:\n%s", addr[0], addr[1], message)

        if message.startswith("SIP/2.0 200"):
            self._handle_200_ok(message)
        elif message.startswith("SIP/2.0 401"):
            self._handle_401_unauthorized(message)
        elif message.startswith("SIP/2.0 403"):
            self._handle_403_forbidden()
        elif message.startswith("INVITE"):
            self._handle_invite(message, addr)
        elif message.startswith("OPTIONS"):
            self._handle_options(message, addr)
        elif message.startswith("NOTIFY"):
            self._handle_notify(message, addr)


class SipProtocol(asyncio.DatagramProtocol):
    """SIP protocol handler."""

    def __init__(self, sip_client: DomruSipClient) -> None:
        """Initialize protocol."""
        self.sip_client = sip_client

    def connection_made(self, transport: asyncio.DatagramTransport) -> None:
        """Handle connection made."""
        _LOGGER.debug("SIP connection established")

    def datagram_received(self, data: bytes, addr: tuple[str, int]) -> None:
        """Handle received datagram."""
        self.sip_client.handle_message(data, addr)

    def error_received(self, exc: Exception) -> None:
        """Handle error."""
        _LOGGER.error("SIP protocol error: %s", exc)

    def connection_lost(self, exc: Exception | None) -> None:
        """Handle connection lost."""
        if exc:
            _LOGGER.error("SIP connection lost: %s", exc)

