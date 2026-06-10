"""Pure Python SIP client for Dom.ru Smart Intercom calls."""

from __future__ import annotations

import asyncio
import hashlib
import logging
import re
import secrets
import socket as sync_socket
import uuid
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from collections.abc import Callable

_LOGGER = logging.getLogger(__name__)

SIP_SERVER_PORT = 5060
DEFAULT_REGISTER_EXPIRES = 30
RE_REGISTER_MARGIN = 5
MAX_AUTH_FAILURES = 2
DEFAULT_CALL_TIMEOUT = 30.0
DEFAULT_RTP_PORT = 10000
DEFAULT_RTCP_PORT = 39996
USER_AGENT = "Myhome/Myhome-android"
MIN_STATUS_PARTS = 2
MIN_CSEQ_PARTS = 2
SIP_STATUS_OK = 200
SIP_STATUS_UNAUTHORIZED = 401
SIP_STATUS_FORBIDDEN = 403

COMPACT_HEADERS = {
    "v": "via",
    "f": "from",
    "t": "to",
    "i": "call-id",
    "m": "contact",
    "l": "content-length",
}
SECRET_HEADERS = {
    "authorization",
    "proxy-authorization",
    "www-authenticate",
    "proxy-authenticate",
}


def _header_key(name: str) -> str:
    """Normalize a SIP header name for case-insensitive lookup."""
    key = name.strip().lower()
    return COMPACT_HEADERS.get(key, key)


def _md5(value: str) -> str:
    """Return an MD5 hex digest for SIP digest authentication."""
    return hashlib.md5(value.encode("utf-8"), usedforsecurity=False).hexdigest()


def _extract_uri(value: str) -> str:
    """Extract a URI from a SIP header value."""
    match = re.search(r"<([^>]+)>", value)
    if match:
        return match.group(1).strip()
    return value.split(";", 1)[0].strip()


def _add_tag(header_value: str, tag: str) -> str:
    """Return a SIP From/To value with exactly one tag parameter."""
    without_tag = re.sub(r";tag=[^;\s>]+", "", header_value, flags=re.IGNORECASE)
    return f"{without_tag};tag={tag}"


def _replace_header_name(header_name: str, line_value: str) -> str:
    """Return a complete SIP header line."""
    return f"{header_name}: {line_value}"


@dataclass(slots=True)
class SipMessage:
    """Minimal SIP message with ordered, repeated headers."""

    start_line: str
    headers: list[tuple[str, str]] = field(default_factory=list)
    body: str = ""

    @classmethod
    def parse(cls, raw: bytes | str) -> SipMessage:
        """Parse a SIP message from bytes or text."""
        text = raw.decode("utf-8", errors="ignore") if isinstance(raw, bytes) else raw
        if "\r\n\r\n" in text:
            head, body = text.split("\r\n\r\n", 1)
        elif "\n\n" in text:
            head, body = text.split("\n\n", 1)
        else:
            head, body = text, ""

        normalized_head = head.replace("\r\n", "\n").replace("\r", "\n")
        lines = normalized_head.split("\n")
        if not lines or not lines[0].strip():
            msg = "SIP message is missing a start line"
            raise ValueError(msg)

        headers: list[tuple[str, str]] = []
        for line in lines[1:]:
            if not line or ":" not in line:
                continue
            name, value = line.split(":", 1)
            headers.append((name.strip(), value.strip()))

        return cls(start_line=lines[0].strip(), headers=headers, body=body)

    @classmethod
    def build(
        cls,
        start_line: str,
        headers: list[tuple[str, str]],
        body: str = "",
    ) -> SipMessage:
        """Build a SIP message."""
        return cls(start_line=start_line, headers=headers, body=body)

    @property
    def is_response(self) -> bool:
        """Return whether the message is a SIP response."""
        return self.start_line.startswith("SIP/2.0 ")

    @property
    def method(self) -> str:
        """Return the request method or CSeq method for responses."""
        if not self.is_response:
            return self.start_line.split(" ", 1)[0].upper()
        return self.cseq_method

    @property
    def status_code(self) -> int | None:
        """Return the SIP response status code."""
        if not self.is_response:
            return None
        parts = self.start_line.split(" ", 2)
        if len(parts) < MIN_STATUS_PARTS:
            return None
        try:
            return int(parts[1])
        except ValueError:
            return None

    @property
    def cseq_method(self) -> str:
        """Return the method named by CSeq."""
        value = self.first_header("CSeq")
        parts = value.split()
        return parts[1].upper() if len(parts) >= MIN_CSEQ_PARTS else ""

    @property
    def cseq_number(self) -> str:
        """Return the CSeq number."""
        value = self.first_header("CSeq")
        parts = value.split()
        return parts[0] if parts else ""

    def header_values(self, name: str) -> list[str]:
        """Return all values for a header name."""
        key = _header_key(name)
        return [value for header, value in self.headers if _header_key(header) == key]

    def first_header(self, name: str, default: str = "") -> str:
        """Return the first value for a header name."""
        values = self.header_values(name)
        return values[0] if values else default

    def to_text(self) -> str:
        """Serialize the SIP message and recalculate Content-Length."""
        header_lines = [
            _replace_header_name(name, value)
            for name, value in self.headers
            if _header_key(name) != "content-length"
        ]
        body_bytes = self.body.encode("utf-8")
        header_lines.append(f"Content-Length: {len(body_bytes)}")
        return (
            self.start_line
            + "\r\n"
            + "\r\n".join(header_lines)
            + "\r\n\r\n"
            + self.body
        )

    def to_bytes(self) -> bytes:
        """Serialize the SIP message as UTF-8 bytes."""
        return self.to_text().encode("utf-8")

    def to_redacted_text(self) -> str:
        """Serialize a log-safe form of the SIP message."""
        header_lines = []
        for name, value in self.headers:
            key = _header_key(name)
            if key in SECRET_HEADERS:
                header_lines.append(f"{name}: <redacted>")
                continue
            safe = re.sub(
                r'(nonce|response|password)="[^"]*"',
                r'\1="<redacted>"',
                value,
            )
            header_lines.append(f"{name}: {safe}")
        header_lines.append(f"Content-Length: {len(self.body.encode('utf-8'))}")
        return (
            self.start_line
            + "\r\n"
            + "\r\n".join(header_lines)
            + "\r\n\r\n"
            + self.body
        )


@dataclass(slots=True)
class DigestAuth:
    """SIP digest authentication challenge."""

    realm: str
    nonce: str
    algorithm: str = "MD5"
    qop: str | None = None

    @classmethod
    def from_header(cls, header_value: str) -> DigestAuth:
        """Parse a WWW-Authenticate Digest header value."""
        value = header_value.strip()
        if value.lower().startswith("digest"):
            value = value[6:].strip()

        params: dict[str, str] = {}
        for match in re.finditer(r"([A-Za-z0-9_-]+)=((?:\"[^\"]*\")|[^,]*)", value):
            key = match.group(1).lower()
            raw_param = match.group(2).strip()
            params[key] = raw_param[1:-1] if raw_param.startswith('"') else raw_param

        qop = params.get("qop")
        selected_qop = None
        if qop and "auth" in [part.strip() for part in qop.split(",")]:
            selected_qop = "auth"

        return cls(
            realm=params.get("realm", ""),
            nonce=params.get("nonce", ""),
            algorithm=params.get("algorithm", "MD5"),
            qop=selected_qop,
        )

    def build_authorization(
        self,
        *,
        username: str,
        password: str,
        method: str,
        uri: str,
        cnonce: str | None = None,
        nc: str = "00000001",
    ) -> str:
        """Build an Authorization header value for this challenge."""
        ha1 = _md5(f"{username}:{self.realm}:{password}")
        ha2 = _md5(f"{method}:{uri}")

        if self.qop == "auth":
            cnonce_value = cnonce or secrets.token_hex(8)
            response = _md5(f"{ha1}:{self.nonce}:{nc}:{cnonce_value}:{self.qop}:{ha2}")
            return (
                f'Digest username="{username}", realm="{self.realm}", '
                f'nonce="{self.nonce}", uri="{uri}", response="{response}", '
                f'algorithm={self.algorithm}, cnonce="{cnonce_value}", '
                f"nc={nc}, qop={self.qop}"
            )

        response = _md5(f"{ha1}:{self.nonce}:{ha2}")
        return (
            f'Digest username="{username}", realm="{self.realm}", '
            f'nonce="{self.nonce}", uri="{uri}", response="{response}", '
            f"algorithm={self.algorithm}"
        )


@dataclass(slots=True)
class SipCall:
    """Active SIP dialog state."""

    invite: SipMessage
    addr: tuple[str, int]
    call_id: str
    local_tag: str
    remote_tag: str
    remote_contact_uri: str
    record_routes: list[str]
    remote_sdp: str
    bye_cseq: int = 0


class DomruSipClient:
    """Small UDP SIP user agent for Dom.ru intercom calls."""

    def __init__(
        self,
        realm: str,
        username: str,
        password: str,
        local_ip: str | None = None,
        local_port: int = SIP_SERVER_PORT,
        on_call_callback: Callable[[dict[str, Any]], None] | None = None,
        registration_mode: str = "persistent",
        call_timeout: float = DEFAULT_CALL_TIMEOUT,
        rtp_port: int = DEFAULT_RTP_PORT,
        rtcp_port: int = DEFAULT_RTCP_PORT,
        server_ip: str | None = None,
    ) -> None:
        """Initialize the SIP client."""
        self.realm = realm
        self.username = username
        self.password = password
        self.local_ip = local_ip or self._get_local_ip()
        self.local_port = local_port
        self.on_call_callback = on_call_callback
        self._registration_mode = registration_mode
        self._call_timeout_seconds = call_timeout
        self._rtp_port = rtp_port
        self._rtcp_port = rtcp_port
        self._server_ip = server_ip
        self._server_addr = (server_ip or realm, SIP_SERVER_PORT)

        self._transport: asyncio.DatagramTransport | None = None
        self._protocol: SipProtocol | None = None
        self._running = False

        self._registration_call_id = ""
        self._registration_tag = ""
        self._cseq = 0
        self._expires = DEFAULT_REGISTER_EXPIRES
        self._registered = False
        self._registered_contact_uri = ""
        self._register_timer: asyncio.TimerHandle | None = None
        self._auth_failure = 0
        self._last_nonce = ""

        self._active_call: SipCall | None = None
        self._call_status = "idle"
        self._call_timer: asyncio.TimerHandle | None = None
        self._pending_hangup_after_ack = False
        self._dialog_cseq = 110
        self._last_error: str | None = None
        self._last_event = "initialized"
        self._last_register_at: str | None = None
        self._last_registered_at: str | None = None

    @staticmethod
    def _tag() -> str:
        """Generate a SIP tag."""
        return secrets.token_hex(4)

    @staticmethod
    def _branch() -> str:
        """Generate a SIP Via branch."""
        return f"z9hG4bK{secrets.token_hex(8)}"

    @staticmethod
    def _instance_id() -> str:
        """Generate a SIP instance identifier."""
        return str(uuid.uuid4())

    def _get_local_ip(self) -> str:
        """Best-effort local IP detection."""
        sock = sync_socket.socket(sync_socket.AF_INET, sync_socket.SOCK_DGRAM)
        try:
            sock.connect(("8.8.8.8", 80))
            return str(sock.getsockname()[0])
        except OSError:
            _LOGGER.exception("Failed to detect local SIP IP")
            return "127.0.0.1"
        finally:
            sock.close()

    @property
    def call_status(self) -> str:
        """Return the current call status."""
        return self._call_status

    @property
    def is_running(self) -> bool:
        """Return whether the UDP socket is running."""
        return self._running

    @property
    def is_registered(self) -> bool:
        """Return whether the client is registered."""
        return self._registered

    @property
    def registration_mode(self) -> str:
        """Return the registration mode."""
        return self._registration_mode

    @property
    def expires(self) -> int:
        """Return the current registration expiry."""
        return self._expires

    @property
    def cseq(self) -> int:
        """Return the registration CSeq."""
        return self._cseq

    @property
    def server_addr(self) -> tuple[str, int]:
        """Return the numeric or configured SIP registrar address."""
        return self._server_addr

    @property
    def last_error(self) -> str | None:
        """Return the last SIP error recorded by the client."""
        return self._last_error

    @property
    def last_event(self) -> str:
        """Return the last SIP lifecycle event recorded by the client."""
        return self._last_event

    @property
    def last_register_at(self) -> str | None:
        """Return when the latest REGISTER was sent."""
        return self._last_register_at

    @property
    def last_registered_at(self) -> str | None:
        """Return when registration last succeeded."""
        return self._last_registered_at

    def get_active_call_info(self) -> dict[str, Any] | None:
        """Return the active call as a dict for Home Assistant attributes."""
        if not self._active_call:
            return None
        invite = self._active_call.invite
        return {
            "from": f"From: {invite.first_header('From')}",
            "to": f"To: {invite.first_header('To')}",
            "call_id": self._active_call.call_id,
            "remote_contact_uri": self._active_call.remote_contact_uri,
            "status": self._call_status,
        }

    async def start(self) -> None:
        """Start the UDP SIP client."""
        if self._running:
            return

        loop = asyncio.get_running_loop()
        await self._resolve_server_addr()
        self._protocol = SipProtocol(self)
        self._transport, _ = await loop.create_datagram_endpoint(
            lambda: self._protocol,
            local_addr=(self.local_ip, self.local_port),
        )
        self._running = True

        _LOGGER.info(
            "SIP client started at %s:%d for %s@%s (%s mode)",
            self.local_ip,
            self.local_port,
            self.username,
            self.realm,
            self._registration_mode,
        )
        if self._registration_mode == "persistent":
            self.register_now(force=True)

    async def stop(self) -> None:
        """Stop the UDP SIP client."""
        if not self._running:
            return

        if self._registered:
            self._send_unregister()

        self._cancel_timers()
        if self._transport:
            self._transport.close()
            self._transport = None
        self._running = False
        self._registered = False
        self._call_status = "idle"
        self._active_call = None

    def register_now(self, *, force: bool = False) -> None:
        """Trigger SIP registration."""
        if not self._running:
            _LOGGER.warning("Cannot register because SIP client is not running")
            return
        if self._registered and not force:
            _LOGGER.debug("Skipping SIP register because client is already registered")
            return

        self._reset_registration()
        self._send_register()

    def re_register(self) -> None:
        """Force a fresh SIP registration."""
        self.register_now(force=True)

    def answer_call(self) -> bool:
        """Answer the current ringing call with 200 OK and SDP."""
        if not self._active_call or self._call_status != "ringing":
            _LOGGER.warning("No ringing SIP call to answer")
            return False

        self._cancel_call_timer()
        self._call_status = "answered"
        _LOGGER.info("Answering SIP call call_id=%s", self._active_call.call_id)
        self._send_invite_ok(self._active_call)
        self._emit_event("call_answered", call_id=self._active_call.call_id)
        return True

    def answer_and_hangup(self) -> bool:
        """Answer an active call and send BYE after ACK arrives."""
        if not self._active_call:
            _LOGGER.info("No active SIP call to answer and hang up")
            return False
        if self._call_status == "ringing":
            self._pending_hangup_after_ack = True
            _LOGGER.info(
                "Answering SIP call and scheduling hangup after ACK call_id=%s",
                self._active_call.call_id,
            )
            return self.answer_call()
        if self._call_status in {"answered", "established"}:
            self._pending_hangup_after_ack = True
            return self.hangup_call()
        return False

    def reject_call(self) -> bool:
        """Reject a ringing call with 486 Busy Here."""
        if not self._active_call or self._call_status != "ringing":
            _LOGGER.warning("No ringing SIP call to reject")
            return False

        self._send_response(
            "486 Busy Here",
            self._active_call.invite,
            to_tag=self._active_call.local_tag,
            extra_headers=[("User-Agent", USER_AGENT)],
            addr=self._active_call.addr,
        )
        _LOGGER.info("Rejected SIP call call_id=%s", self._active_call.call_id)
        self._end_call()
        return True

    def hangup_call(self) -> bool:
        """Hang up the active call."""
        if not self._active_call:
            _LOGGER.warning("No active SIP call to hang up")
            return False
        if self._call_status == "ringing":
            return self.reject_call()
        if self._call_status == "answered":
            self._pending_hangup_after_ack = True
            _LOGGER.info(
                "SIP call answered; BYE will be sent after ACK call_id=%s",
                self._active_call.call_id,
            )
            return True
        if self._call_status == "established":
            self._send_bye(self._active_call)
            self._call_status = "ending"
            _LOGGER.info("Sent SIP BYE call_id=%s", self._active_call.call_id)
            self._emit_event("call_hangup_sent", call_id=self._active_call.call_id)
            return True
        return self._call_status == "ending"

    def handle_message(self, data: bytes, addr: tuple[str, int]) -> None:
        """Handle an inbound SIP datagram."""
        try:
            message = SipMessage.parse(data)
        except ValueError:
            _LOGGER.debug("Ignoring invalid SIP datagram from %s:%d", addr[0], addr[1])
            return

        self._log_wire("<<<", message, addr)
        if message.is_response:
            self._handle_response(message)
            return
        self._handle_request(message, addr)

    def simulate_incoming_call(self) -> None:
        """Inject a synthetic INVITE for Home Assistant service testing."""
        invite = (
            f"INVITE sip:{self.username}@{self.realm} SIP/2.0\r\n"
            f"Via: SIP/2.0/UDP {self.realm}:{SIP_SERVER_PORT};branch=z9hG4bKtest\r\n"
            f'From: "Test Caller" <sip:test@{self.realm}>;tag=test123\r\n'
            f"To: <sip:{self.username}@{self.realm}>\r\n"
            f"Call-ID: test-call-{self._tag()}\r\n"
            f"CSeq: 1 INVITE\r\n"
            f"Contact: <sip:test@{self.realm}:{SIP_SERVER_PORT}>\r\n"
            f"Content-Length: 0\r\n\r\n"
        )
        self.handle_message(invite.encode("utf-8"), (self.realm, SIP_SERVER_PORT))

    def _reset_registration(self) -> None:
        """Reset registration identifiers."""
        self._registration_call_id = str(uuid.uuid4())
        self._registration_tag = self._tag()
        self._cseq = 1
        self._expires = DEFAULT_REGISTER_EXPIRES
        self._registered = False
        self._auth_failure = 0
        self._last_nonce = ""
        if self._register_timer:
            self._register_timer.cancel()
            self._register_timer = None

    async def _resolve_server_addr(self) -> None:
        """Resolve registrar host once so UDP sendto receives a numeric IP."""
        if self._server_ip:
            self._server_addr = (self._server_ip, SIP_SERVER_PORT)
            _LOGGER.info(
                "Using configured SIP registrar IP %s:%d for realm %s",
                self._server_addr[0],
                self._server_addr[1],
                self.realm,
            )
            return

        try:
            infos = await asyncio.get_running_loop().getaddrinfo(
                self.realm,
                SIP_SERVER_PORT,
                family=sync_socket.AF_INET,
                type=sync_socket.SOCK_DGRAM,
            )
        except OSError:
            self._record_error(f"failed to resolve SIP registrar {self.realm}")
            _LOGGER.exception("Failed to resolve SIP registrar %s", self.realm)
            return

        if infos:
            sockaddr = infos[0][4]
            self._server_addr = (sockaddr[0], sockaddr[1])
            _LOGGER.info(
                "Resolved SIP registrar %s to %s:%d",
                self.realm,
                self._server_addr[0],
                self._server_addr[1],
            )

    def _build_register(
        self,
        *,
        authorization: str | None = None,
        expires: int | None = None,
    ) -> SipMessage:
        """Build a REGISTER message."""
        expires_value = self._expires if expires is None else expires
        instance_id = self._instance_id()
        headers = [
            (
                "Via",
                f"SIP/2.0/UDP {self.local_ip}:{self.local_port};"
                f"branch={self._branch()};rport",
            ),
            ("Max-Forwards", "70"),
            (
                "From",
                f"<sip:{self.username}@{self.realm}>;tag={self._registration_tag}",
            ),
            ("To", f"<sip:{self.username}@{self.realm}>"),
            ("Call-ID", self._registration_call_id),
            ("CSeq", f"{self._cseq} REGISTER"),
            (
                "Contact",
                f"<sip:{self.username}@{self.local_ip}:{self.local_port};"
                f'transport=udp>;+sip.instance="<urn:uuid:{instance_id}>"',
            ),
            ("User-Agent", USER_AGENT),
            ("Supported", "replaces, outbound, gruu, path"),
            ("Expires", str(expires_value)),
        ]
        if authorization:
            headers.append(("Authorization", authorization))
        return SipMessage.build(
            f"REGISTER sip:{self.realm} SIP/2.0",
            headers,
        )

    def _send_register(self, authorization: str | None = None) -> None:
        """Send REGISTER to the SIP server."""
        self._last_register_at = self._now()
        self._last_event = "register_sent"
        _LOGGER.info(
            "Sending SIP REGISTER cseq=%d expires=%ds registrar=%s:%d "
            "local=%s:%d auth=%s",
            self._cseq,
            self._expires,
            self._server_addr[0],
            self._server_addr[1],
            self.local_ip,
            self.local_port,
            "yes" if authorization else "no",
        )
        self._send_to_server(self._build_register(authorization=authorization))

    def _send_unregister(self) -> None:
        """Send unregister request."""
        self._cseq += 1
        self._send_to_server(self._build_register(expires=0))
        self._registered = False

    def _handle_response(self, message: SipMessage) -> None:
        """Handle a SIP response."""
        status = message.status_code
        method = message.cseq_method
        if status == SIP_STATUS_UNAUTHORIZED and method == "REGISTER":
            self._handle_register_challenge(message)
            return
        if status == SIP_STATUS_FORBIDDEN and method == "REGISTER":
            self._record_error("registration forbidden")
            _LOGGER.error("SIP registration rejected with 403 Forbidden")
            self._registered = False
            self._emit_event("registration_failed", error=self._last_error)
            return
        if status == SIP_STATUS_OK and method == "REGISTER":
            self._handle_register_ok(message)
            return
        if (
            status == SIP_STATUS_OK
            and method == "BYE"
            and self._call_status == "ending"
        ):
            self._end_call()

    def _handle_register_challenge(self, message: SipMessage) -> None:
        """Respond to REGISTER 401 challenge."""
        challenge_header = message.first_header(
            "WWW-Authenticate"
        ) or message.first_header("Proxy-Authenticate")
        if not challenge_header:
            self._record_error("registration challenge missing digest")
            _LOGGER.error("SIP 401 response did not include a digest challenge")
            self._emit_event("registration_failed", error=self._last_error)
            return

        challenge = DigestAuth.from_header(challenge_header)
        _LOGGER.info("Received SIP REGISTER challenge for realm %s", challenge.realm)
        if self._last_nonce == challenge.nonce:
            self._auth_failure += 1
        else:
            self._auth_failure = 1
            self._last_nonce = challenge.nonce

        if self._auth_failure >= MAX_AUTH_FAILURES:
            self._record_error("digest authentication failed repeatedly")
            _LOGGER.error("SIP digest authentication failed repeatedly")
            self._emit_event("registration_failed", error=self._last_error)
            return

        self._cseq += 1
        auth = challenge.build_authorization(
            username=self.username,
            password=self.password,
            method="REGISTER",
            uri=f"sip:{self.realm}",
        )
        self._send_register(auth)

    def _handle_register_ok(self, message: SipMessage) -> None:
        """Handle successful REGISTER."""
        contact = message.first_header("Contact")
        pub_gruu = re.search(r'pub-gruu="([^"]+)"', contact, flags=re.IGNORECASE)
        if pub_gruu:
            self._registered_contact_uri = pub_gruu.group(1)
        elif contact:
            self._registered_contact_uri = _extract_uri(contact)

        expires_match = re.search(r"expires=(\d+)", contact, flags=re.IGNORECASE)
        if not expires_match:
            expires_match = re.search(
                r"^(\d+)$",
                message.first_header("Expires"),
                flags=re.IGNORECASE,
            )
        if expires_match:
            self._expires = int(expires_match.group(1))

        if self._expires <= 0:
            self._registered = False
            _LOGGER.info("SIP unregistered successfully")
            return

        self._registered = True
        self._auth_failure = 0
        self._last_error = None
        self._last_registered_at = self._now()
        self._last_event = "registered"
        _LOGGER.info(
            "SIP registration succeeded expires=%ds contact=%s next_refresh_in=%ss",
            self._expires,
            self._registered_contact_uri or "-",
            max(self._expires - RE_REGISTER_MARGIN, 1),
        )
        self._emit_event("registered", expires=self._expires)
        self._schedule_register()

    def _schedule_register(self) -> None:
        """Schedule re-registration before expiry."""
        if not self._running:
            return
        if self._register_timer:
            self._register_timer.cancel()
        delay = max(float(self._expires - RE_REGISTER_MARGIN), 1.0)
        _LOGGER.debug("Scheduling SIP re-register in %.1fs", delay)
        self._register_timer = self._loop().call_later(delay, self._do_register)

    def _do_register(self) -> None:
        """Send a refresh REGISTER."""
        self._cseq += 1
        _LOGGER.info("Refreshing SIP registration cseq=%d", self._cseq)
        self._send_register()

    def _handle_request(self, message: SipMessage, addr: tuple[str, int]) -> None:
        """Dispatch a SIP request."""
        method = message.method
        if method == "INVITE":
            self._handle_invite(message, addr)
        elif method == "ACK":
            self._handle_ack(message)
        elif method == "BYE":
            self._handle_remote_bye(message, addr)
        elif method == "CANCEL":
            self._handle_cancel(message, addr)
        elif method in {"OPTIONS", "NOTIFY", "INFO"}:
            self._send_response("200 OK", message, to_tag=self._tag(), addr=addr)
        else:
            _LOGGER.debug("Unhandled SIP request method: %s", method)

    def _handle_invite(self, message: SipMessage, addr: tuple[str, int]) -> None:
        """Handle inbound intercom INVITE."""
        call_id = message.first_header("Call-ID")
        if self._active_call and self._active_call.call_id == call_id:
            if self._call_status == "ringing":
                self._send_trying(self._active_call)
            elif self._call_status in {"answered", "established"}:
                self._send_invite_ok(self._active_call)
            return

        if self._active_call:
            temp_call = self._call_from_invite(message, addr)
            self._send_response(
                "486 Busy Here",
                temp_call.invite,
                to_tag=temp_call.local_tag,
                addr=temp_call.addr,
            )
            return

        self._active_call = self._call_from_invite(message, addr)
        self._call_status = "ringing"
        self._last_event = "incoming_call"
        self._pending_hangup_after_ack = False
        _LOGGER.info(
            "Incoming SIP INVITE call_id=%s from=%s contact=%s addr=%s:%d",
            call_id,
            message.first_header("From"),
            message.first_header("Contact"),
            addr[0],
            addr[1],
        )
        self._send_trying(self._active_call)
        self._schedule_call_timeout()
        self._emit_event(
            "incoming_call",
            from_header=message.first_header("From"),
            from_=message.first_header("From"),
            call_id=call_id,
        )

    def _call_from_invite(
        self,
        message: SipMessage,
        addr: tuple[str, int],
    ) -> SipCall:
        """Create call state from INVITE."""
        return SipCall(
            invite=message,
            addr=addr,
            call_id=message.first_header("Call-ID"),
            local_tag=self._tag(),
            remote_tag=self._remote_tag(message.first_header("From")),
            remote_contact_uri=_extract_uri(message.first_header("Contact")),
            record_routes=message.header_values("Record-Route"),
            remote_sdp=message.body,
        )

    def _handle_ack(self, message: SipMessage) -> None:
        """Handle ACK for answered INVITE."""
        if not self._active_call:
            return
        if message.first_header("Call-ID") != self._active_call.call_id:
            return
        if self._call_status == "answered":
            self._call_status = "established"
            _LOGGER.info("SIP call established call_id=%s", self._active_call.call_id)
            self._emit_event("call_established", call_id=self._active_call.call_id)
        if self._pending_hangup_after_ack:
            self.hangup_call()

    def _handle_cancel(self, message: SipMessage, addr: tuple[str, int]) -> None:
        """Handle CANCEL for a ringing INVITE."""
        self._send_response("200 OK", message, addr=addr)
        if self._active_call:
            self._send_response(
                "487 Request Terminated",
                self._active_call.invite,
                to_tag=self._active_call.local_tag,
                addr=self._active_call.addr,
            )
        self._end_call()

    def _handle_remote_bye(self, message: SipMessage, addr: tuple[str, int]) -> None:
        """Handle BYE sent by the remote side."""
        self._send_response("200 OK", message, addr=addr)
        self._end_call()

    def _send_trying(self, call: SipCall) -> None:
        """Send 100 Trying without a To tag."""
        self._send_response("100 Trying", call.invite, addr=call.addr)

    def _send_invite_ok(self, call: SipCall) -> None:
        """Send 200 OK for INVITE with minimal SDP."""
        contact_uri = (
            self._registered_contact_uri or f"sip:{self.username}@{self.realm}"
        )
        body = (
            "v=0\r\n"
            f"o={self.username} {secrets.randbelow(9000) + 1000} "
            f"{secrets.randbelow(9000) + 1000} IN IP4 {self.local_ip}\r\n"
            "s=Talk\r\n"
            f"c=IN IP4 {self.local_ip}\r\n"
            "t=0 0\r\n"
            f"m=audio {self._rtp_port} RTP/AVP 0 8 101\r\n"
            "a=rtpmap:101 telephone-event/8000\r\n"
            f"a=rtcp:{self._rtcp_port}\r\n"
        )
        extra_headers = [
            ("Contact", f"<{contact_uri}>"),
            *[("Record-Route", value) for value in call.record_routes],
            ("User-Agent", USER_AGENT),
            (
                "Allow",
                "INVITE, ACK, CANCEL, OPTIONS, BYE, REFER, NOTIFY, MESSAGE, "
                "SUBSCRIBE, INFO, PRACK, UPDATE",
            ),
            ("Supported", "replaces, outbound, gruu, path"),
            ("Content-Type", "application/sdp"),
        ]
        self._send_response(
            "200 OK",
            call.invite,
            to_tag=call.local_tag,
            extra_headers=extra_headers,
            body=body,
            addr=call.addr,
        )

    def _send_response(
        self,
        status: str,
        request: SipMessage,
        *,
        addr: tuple[str, int],
        to_tag: str | None = None,
        extra_headers: list[tuple[str, str]] | None = None,
        body: str = "",
    ) -> None:
        """Build and send a SIP response."""
        headers: list[tuple[str, str]] = []
        headers.extend(("Via", value) for value in request.header_values("Via"))
        if request.first_header("From"):
            headers.append(("From", request.first_header("From")))
        if request.first_header("To"):
            to_value = request.first_header("To")
            headers.append(("To", _add_tag(to_value, to_tag) if to_tag else to_value))
        if request.first_header("Call-ID"):
            headers.append(("Call-ID", request.first_header("Call-ID")))
        if request.first_header("CSeq"):
            headers.append(("CSeq", request.first_header("CSeq")))
        if extra_headers:
            headers.extend(extra_headers)

        self._send_to_addr(SipMessage.build(f"SIP/2.0 {status}", headers, body), addr)

    def _send_bye(self, call: SipCall) -> None:
        """Send BYE for an established dialog."""
        self._dialog_cseq += 1
        call.bye_cseq = self._dialog_cseq
        headers: list[tuple[str, str]] = [
            (
                "Via",
                f"SIP/2.0/UDP {self.local_ip}:{self.local_port};"
                f"branch={self._branch()};rport",
            ),
            *[("Route", value) for value in call.record_routes],
            ("Max-Forwards", "70"),
            ("From", f"<sip:{self.username}@{self.realm}>;tag={call.local_tag}"),
            ("To", call.invite.first_header("From")),
            ("Call-ID", call.call_id),
            ("CSeq", f"{call.bye_cseq} BYE"),
            ("User-Agent", USER_AGENT),
        ]
        bye = SipMessage.build(
            f"BYE {call.remote_contact_uri} SIP/2.0",
            headers,
        )
        self._send_to_addr(bye, call.addr)

    def _send_to_server(self, message: SipMessage) -> None:
        """Send a SIP message to the registrar."""
        self._send_to_addr(message, self._server_addr)

    def _send_to_addr(self, message: SipMessage, addr: tuple[str, int]) -> None:
        """Send a SIP message to an address."""
        self._log_wire(">>>", message, addr)
        if self._transport:
            self._transport.sendto(message.to_bytes(), addr)

    def _schedule_call_timeout(self) -> None:
        """Schedule automatic busy response for unanswered calls."""
        self._cancel_call_timer()
        if self._call_timeout_seconds <= 0:
            return
        self._call_timer = self._loop().call_later(
            self._call_timeout_seconds,
            self._auto_reject_call,
        )

    def _auto_reject_call(self) -> None:
        """Reject a ringing call after timeout."""
        if self._active_call and self._call_status == "ringing":
            _LOGGER.info(
                "Auto-rejecting unanswered SIP call after %.1fs call_id=%s",
                self._call_timeout_seconds,
                self._active_call.call_id,
            )
            self.reject_call()

    def _end_call(self) -> None:
        """Clear active call state."""
        call_id = self._active_call.call_id if self._active_call else "-"
        self._cancel_call_timer()
        self._active_call = None
        self._call_status = "idle"
        self._pending_hangup_after_ack = False
        _LOGGER.info("SIP call cleared call_id=%s", call_id)
        self._emit_event("call_ended")
        if self._registration_mode == "on_demand" and self._registered:
            self._loop().call_later(5.0, self._send_unregister)

    def _cancel_call_timer(self) -> None:
        """Cancel the active call timeout."""
        if self._call_timer:
            self._call_timer.cancel()
            self._call_timer = None

    def _cancel_timers(self) -> None:
        """Cancel all timers."""
        self._cancel_call_timer()
        if self._register_timer:
            self._register_timer.cancel()
            self._register_timer = None

    def _loop(self) -> asyncio.AbstractEventLoop:
        """Return the current event loop."""
        try:
            return asyncio.get_running_loop()
        except RuntimeError:
            return asyncio.get_event_loop()

    def _emit_event(self, event: str, **data: Any) -> None:
        """Emit a callback event if configured."""
        self._last_event = event
        if self.on_call_callback:
            payload = {"event": event, **data}
            if "from_" in payload:
                payload["from"] = payload.pop("from_")
            self.on_call_callback(payload)

    @staticmethod
    def _now() -> str:
        """Return a UTC timestamp for diagnostics."""
        return datetime.now(UTC).isoformat()

    def _record_error(self, error: str) -> None:
        """Store and log the last SIP error for entity diagnostics."""
        self._last_error = error
        self._last_event = "error"

    def _log_wire(
        self,
        direction: str,
        message: SipMessage,
        addr: tuple[str, int],
    ) -> None:
        """Log a redacted SIP wire message."""
        _LOGGER.debug(
            "%s SIP %s:%d %s\n%s",
            direction,
            addr[0],
            addr[1],
            message.start_line,
            message.to_redacted_text().strip(),
        )

    @staticmethod
    def _remote_tag(from_header: str) -> str:
        """Extract the remote tag from a From header value."""
        match = re.search(r";tag=([^;\s>]+)", from_header, flags=re.IGNORECASE)
        return match.group(1) if match else ""


class SipProtocol(asyncio.DatagramProtocol):
    """Asyncio UDP protocol adapter for DomruSipClient."""

    def __init__(self, sip_client: DomruSipClient) -> None:
        """Initialize the protocol."""
        self.sip_client = sip_client

    def connection_made(self, _transport: asyncio.DatagramTransport) -> None:
        """Handle UDP socket creation."""
        _LOGGER.debug("SIP UDP socket ready")

    def datagram_received(self, data: bytes, addr: tuple[str, int]) -> None:
        """Forward inbound datagrams to the SIP client."""
        self.sip_client.handle_message(data, addr)

    def error_received(self, exc: Exception) -> None:
        """Log UDP errors."""
        _LOGGER.error("SIP UDP error: %s", exc)

    def connection_lost(self, exc: Exception | None) -> None:
        """Log unexpected UDP socket closure."""
        if exc:
            _LOGGER.error("SIP UDP socket closed with error: %s", exc)
