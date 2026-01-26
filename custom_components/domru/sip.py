"""SIP client for Dom.ru Smart Intercom to receive incoming calls."""

from __future__ import annotations

import asyncio
import hashlib
import logging
import re
import secrets
import socket as sync_socket
import uuid
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from collections.abc import Callable

_LOGGER = logging.getLogger(__name__)

# Constants
MAX_AUTH_FAILURES = 2


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

        # Active call state
        self._active_call: dict[str, Any] | None = None
        self._active_call_timer: asyncio.TimerHandle | None = None
        self._call_status = "idle"  # idle, ringing, answered

    def _get_local_ip(self) -> str:
        """Get local IP address."""
        try:
            # Create a socket to determine the local IP
            s = sync_socket.socket(sync_socket.AF_INET, sync_socket.SOCK_DGRAM)
            s.connect(("8.8.8.8", 80))
            local_ip = s.getsockname()[0]
        except OSError:
            _LOGGER.exception("Failed to get local IP")
            return "127.0.0.1"
        else:
            s.close()
            return local_ip

    @property
    def call_status(self) -> str:
        """Return current call status."""
        return self._call_status

    @property
    def is_running(self) -> bool:
        """Return whether SIP client is running."""
        return self._running

    @property
    def expires(self) -> int:
        """Return registration expiration time."""
        return self._expires

    @property
    def cseq(self) -> int:
        """Return current CSeq number."""
        return self._cseq

    def get_active_call_info(self) -> dict[str, Any] | None:
        """Return active call information."""
        return self._active_call

    def answer_call(self) -> bool:
        """Answer the current incoming call."""
        if not self._active_call or self._call_status != "ringing":
            _LOGGER.warning("No incoming call to answer")
            return False

        _LOGGER.info("Answering call %s", self._active_call.get("call_id"))
        self._call_status = "answered"
        self._send_200_ok(self._active_call)

        # Notify status change
        if self.on_call_callback:
            self.on_call_callback(
                {
                    "event": "call_answered",
                    "call_id": self._active_call.get("call_id"),
                }
            )

        return True

    def reject_call(self) -> bool:
        """Reject the current incoming call."""
        if not self._active_call or self._call_status != "ringing":
            _LOGGER.warning("No incoming call to reject")
            return False

        _LOGGER.info("Rejecting call %s", self._active_call.get("call_id"))
        self._send_busy(self._active_call)
        self._end_call()

        return True

    def _end_call(self) -> None:
        """End the current call."""
        if self._active_call_timer:
            self._active_call_timer.cancel()
            self._active_call_timer = None

        self._active_call = None
        self._call_status = "idle"

        # Notify status change
        if self.on_call_callback:
            self.on_call_callback(
                {
                    "event": "call_ended",
                }
            )

    @staticmethod
    def _md5(s: str) -> str:
        """Calculate MD5 hash."""
        return hashlib.md5(s.encode(), usedforsecurity=False).hexdigest()

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
            f"Via: SIP/2.0/UDP {self.local_ip}:{self.local_port};"
            f"branch=z9hG4bK{self._tag()};rport\r\n"
            f"Max-Forwards: 70\r\n"
            f"From: <sip:{self.username}@{self.realm}>;tag={self._tag()}\r\n"
            f"To: <sip:{self.username}@{self.realm}>\r\n"
            f"Call-ID: {self._call_id}\r\n"
            f"CSeq: {self._cseq} REGISTER\r\n"
            f"Contact: <sip:{self.username}@{self.local_ip}:{self.local_port};ob>;"
            f"reg-id=42;expires={expires_value}\r\n"
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

        try:
            loop = asyncio.get_event_loop()

            self._protocol = SipProtocol(self)
            self._transport, _ = await loop.create_datagram_endpoint(
                lambda: self._protocol,
                local_addr=(self.local_ip, self.local_port),
            )

            self._running = True
            self._unregister()
            self._send_register()

            _LOGGER.info(
                "SIP client bound to %s:%d, ready to receive calls",
                self.local_ip,
                self.local_port,
            )
        except OSError:
            _LOGGER.exception(
                "Failed to bind SIP client to %s:%d - %s. "
                "Port might be in use or you may need to run as administrator.",
                self.local_ip,
                self.local_port,
                OSError.__name__,
            )
            raise

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

        exp_match = re.search(r"Expires:\s*(\d+)", message, re.IGNORECASE)
        if exp_match and int(exp_match.group(1)) > 0:
            self._expires = int(exp_match.group(1))

        if self._cseq == 1:
            # First registration, send again with credentials
            _LOGGER.info(
                "SIP: Initial registration OK, sending authenticated registration"
            )
            asyncio.get_event_loop().call_later(0.25, self._send_register)
        else:
            # Schedule next registration
            _LOGGER.info(
                "SIP: Registration successful, next registration in %d seconds",
                self._expires - 5,
            )
            self._schedule_register()

    def _handle_401_unauthorized(self, message: str) -> None:
        """Handle 401 Unauthorized response."""
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

        if self._auth_failure >= MAX_AUTH_FAILURES:
            _LOGGER.error("SIP authentication failed - invalid credentials")
            return

        _LOGGER.info(
            "SIP: Received 401, sending authenticated REGISTER (attempt %d)",
            self._auth_failure,
        )
        self._cseq += 1
        auth = self._build_auth(realm, nonce)
        self._send_register(auth)

    def _handle_403_forbidden(self) -> None:
        """Handle 403 Forbidden response."""
        _LOGGER.error("SIP registration forbidden (403)")

    def _handle_invite(self, message: str, addr: tuple[str, int]) -> None:
        """Handle incoming INVITE (call)."""
        # Extract SIP headers
        headers = self._extract_headers(message)
        call_id = headers.get("call_id", "").replace("i:", "").strip()

        # Check if this is a retransmission of the same call
        if self._active_call and self._active_call.get("call_id") == call_id:
            # Retransmission - just resend 100 Trying
            _LOGGER.debug("Retransmission of call %s", call_id)
            self._send_trying(self._active_call)
            return

        _LOGGER.info("=" * 60)
        _LOGGER.info("INCOMING SIP CALL from %s:%d", addr[0], addr[1])
        _LOGGER.info("=" * 60)

        # Parse caller info
        from_header = headers.get("from", "Unknown")
        _LOGGER.info("From: %s", from_header)
        _LOGGER.info("To: %s", headers.get("to", "Unknown"))
        _LOGGER.info("Call-ID: %s", call_id)

        # Store call information
        self._active_call = {
            "message": message,
            "addr": addr,
            "headers": headers,
            "from": from_header,
            "to": headers.get("to"),
            "call_id": call_id,
        }
        self._call_status = "ringing"

        # Send 100 Trying and 180 Ringing
        self._send_trying(self._active_call)
        loop = asyncio.get_event_loop()
        loop.call_later(0.150, lambda: self._send_ringing(self._active_call))

        # Auto-reject after 30 seconds if not answered
        if self._active_call_timer:
            self._active_call_timer.cancel()
        self._active_call_timer = loop.call_later(30.0, self._auto_reject_call)

        # Notify about incoming call
        if self.on_call_callback:
            self.on_call_callback(
                {
                    "event": "incoming_call",
                    "from": from_header,
                    "to": headers.get("to"),
                    "call_id": call_id,
                }
            )
        else:
            _LOGGER.warning("No callback configured for incoming call")

        _LOGGER.info("=" * 60)

    def _extract_headers(self, message: str) -> dict[str, str]:
        """Extract common SIP headers."""

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

    def _auto_reject_call(self) -> None:
        """Auto-reject call after timeout."""
        if self._active_call and self._call_status == "ringing":
            _LOGGER.info("Auto-rejecting call after timeout")
            self._send_busy(self._active_call)
            self._end_call()

    def _send_trying(self, call_info: dict[str, Any]) -> None:
        """Send 100 Trying response."""
        if not self._transport:
            return

        headers = call_info["headers"]
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

        self._transport.sendto(trying.encode(), call_info["addr"])

    def _send_ringing(self, call_info: dict[str, Any]) -> None:
        """Send 180 Ringing response."""
        if not self._transport or not call_info:
            return

        headers = call_info["headers"]
        to_tag = self._tag()

        ringing = (
            f"SIP/2.0 180 Ringing\r\n"
            f"{headers['via']}\r\n"
            f"{headers['from']}\r\n"
            f"{headers['to']};tag={to_tag}\r\n"
            f"{headers['call_id']}\r\n"
            f"{headers['cseq']}\r\n"
            f"Content-Length: 0\r\n\r\n"
        )

        self._transport.sendto(ringing.encode(), call_info["addr"])

    def _send_200_ok(self, call_info: dict[str, Any]) -> None:
        """Send 200 OK response (answer call)."""
        if not self._transport:
            return

        headers = call_info["headers"]
        to_tag = self._tag()

        ok = (
            f"SIP/2.0 200 OK\r\n"
            f"{headers['via']}\r\n"
            f"{headers['from']}\r\n"
            f"{headers['to']};tag={to_tag}\r\n"
            f"{headers['call_id']}\r\n"
            f"{headers['cseq']}\r\n"
            f"Contact: <sip:{self.username}@{self.local_ip}:{self.local_port}>\r\n"
            f"Content-Type: application/sdp\r\n"
            f"Content-Length: 0\r\n\r\n"
        )

        self._transport.sendto(ok.encode(), call_info["addr"])

    def _send_busy(self, call_info: dict[str, Any]) -> None:
        """Send 486 Busy Here response (reject call)."""
        if not self._transport:
            return

        headers = call_info["headers"]
        to_tag = self._tag()

        busy = (
            f"SIP/2.0 486 Busy Here\r\n"
            f"{headers['via']}\r\n"
            f"{headers['from']}\r\n"
            f"{headers['to']};tag={to_tag}\r\n"
            f"{headers['call_id']}\r\n"
            f"{headers['cseq']}\r\n"
            f"Content-Length: 0\r\n\r\n"
        )

        self._transport.sendto(busy.encode(), call_info["addr"])

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

    def _handle_ack(self, message: str, addr: tuple[str, int]) -> None:  # noqa: ARG002
        """Handle ACK request."""
        _LOGGER.debug("Received ACK for answered call")
        # ACK confirms 200 OK, call is now established

    def _handle_bye(self, message: str, addr: tuple[str, int]) -> None:
        """Handle BYE request (call termination)."""
        headers = self._extract_headers(message)

        _LOGGER.info("Call ended by remote party")

        # Send 200 OK response
        ok = (
            f"SIP/2.0 200 OK\r\n"
            f"{headers['via']}\r\n"
            f"{headers['from']}\r\n"
            f"{headers['to']}\r\n"
            f"{headers['call_id']}\r\n"
            f"{headers['cseq']}\r\n"
            f"Content-Length: 0\r\n\r\n"
        )

        if self._transport:
            self._transport.sendto(ok.encode(), addr)

        # End the call
        self._end_call()

    def _handle_cancel(self, message: str, addr: tuple[str, int]) -> None:
        """Handle CANCEL request (call cancellation)."""
        headers = self._extract_headers(message)

        _LOGGER.info("Call cancelled by remote party")

        # Send 200 OK response to CANCEL
        ok = (
            f"SIP/2.0 200 OK\r\n"
            f"{headers['via']}\r\n"
            f"{headers['from']}\r\n"
            f"{headers['to']}\r\n"
            f"{headers['call_id']}\r\n"
            f"{headers['cseq']}\r\n"
            f"Content-Length: 0\r\n\r\n"
        )

        if self._transport:
            self._transport.sendto(ok.encode(), addr)

        # End the call
        self._end_call()

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
        elif message.startswith("ACK"):
            self._handle_ack(message, addr)
        elif message.startswith("BYE"):
            self._handle_bye(message, addr)
        elif message.startswith("CANCEL"):
            self._handle_cancel(message, addr)
        elif message.startswith("OPTIONS"):
            self._handle_options(message, addr)
        elif message.startswith("NOTIFY"):
            self._handle_notify(message, addr)

    def simulate_incoming_call(self) -> None:
        """Simulate an incoming call for testing purposes."""
        if not self._running:
            _LOGGER.warning("Cannot simulate call - SIP client not running")
            return

        _LOGGER.info("=" * 60)
        _LOGGER.info("SIMULATING INCOMING SIP CALL (TEST)")
        _LOGGER.info("=" * 60)

        # Create test INVITE message
        test_invite = (
            f"INVITE sip:{self.username}@{self.local_ip}:{self.local_port} SIP/2.0\r\n"
            f"Via: SIP/2.0/UDP {self.realm}:5060;branch=z9hG4bKtest\r\n"
            f'From: "Test Caller" <sip:test@{self.realm}>;tag=test123\r\n'
            f"To: <sip:{self.username}@{self.realm}>\r\n"
            f"Call-ID: test-call-{self._tag()}\r\n"
            f"CSeq: 1 INVITE\r\n"
            f"Contact: <sip:test@{self.realm}:5060>\r\n"
            f"Content-Length: 0\r\n\r\n"
        )

        # Simulate receiving this message from the server
        self._handle_invite(test_invite, (self.realm, 5060))

        _LOGGER.info("Test call simulation completed")
        _LOGGER.info("=" * 60)


class SipProtocol(asyncio.DatagramProtocol):
    """SIP protocol handler."""

    def __init__(self, sip_client: DomruSipClient) -> None:
        """Initialize protocol."""
        self.sip_client = sip_client

    def connection_made(self, _transport: asyncio.DatagramTransport) -> None:
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
