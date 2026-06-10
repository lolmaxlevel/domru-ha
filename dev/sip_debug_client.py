#!/usr/bin/env python3
# ruff: noqa: T201
"""Standalone Dom.ru SIP debug client with redacted wire logs."""

from __future__ import annotations

import argparse
import asyncio
import base64
import hashlib
import importlib.util
import logging
import os
import signal
import socket
import sys
from collections import deque
from contextlib import suppress
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import TYPE_CHECKING, Any
from urllib.parse import urljoin, urlparse
from uuid import NAMESPACE_URL, UUID, uuid5

if TYPE_CHECKING:
    from collections.abc import Deque
    from types import ModuleType

BASE_URL = "https://myhome.proptech.ru/"
API_HOST = urlparse(BASE_URL).hostname or "myhome.proptech.ru"
USER_AGENT = (
    "Google sdkgphone64x8664 | Android 14 | erth | 8.9.2 (8090200) |  | "
    "null | 10c99d90-9899-4a25-926f-067b34bc4a7f | null"
)
HASH2_PREFIX = "DigitalHomeNTK"
HASH2_SECRET = "789sdgHJs678wertv34712376"  # noqa: S105
MAX_RECENT_LOGS = 12


@dataclass(slots=True)
class DebugApiRuntime:
    """Authenticated Dom.ru API context kept alive for door-open commands."""

    session: Any
    headers: dict[str, str]
    place_id: str
    access_control_id: str

    async def open_door(self) -> Any:
        """Send the Dom.ru accessControlOpen action."""
        return await _request_json(
            self.session,
            method="POST",
            url=urljoin(
                BASE_URL,
                "rest/v1/places/"
                f"{self.place_id}/accesscontrols/{self.access_control_id}/actions",
            ),
            headers=self.headers,
            json_data={"name": "accessControlOpen"},
        )

    async def close(self) -> None:
        """Close the underlying HTTP session."""
        await self.session.close()


class StaticHostResolver:
    """aiohttp-compatible resolver with explicit host-to-IP overrides."""

    def __init__(self, overrides: dict[str, str]) -> None:
        """Initialize host overrides."""
        self._overrides = {host.lower(): ip for host, ip in overrides.items()}

    async def resolve(
        self,
        host: str,
        port: int = 0,
        family: int = socket.AF_INET,
    ) -> list[dict[str, Any]]:
        """Resolve host, using an override when configured."""
        override = self._overrides.get(host.lower())
        if override:
            return [
                {
                    "hostname": host,
                    "host": override,
                    "port": port,
                    "family": family,
                    "proto": 0,
                    "flags": 0,
                }
            ]

        infos = await asyncio.get_running_loop().getaddrinfo(
            host,
            port,
            type=socket.SOCK_STREAM,
            family=family,
        )
        return [
            {
                "hostname": host,
                "host": sockaddr[0],
                "port": sockaddr[1],
                "family": addr_family,
                "proto": proto,
                "flags": 0,
            }
            for addr_family, _socktype, proto, _canonname, sockaddr in infos
        ]

    async def close(self) -> None:
        """Close resolver resources."""


class RecentLogHandler(logging.Handler):
    """Logging handler that keeps recent lines for the TUI."""

    def __init__(self, max_lines: int = MAX_RECENT_LOGS) -> None:
        """Initialize recent log storage."""
        super().__init__()
        self.lines: Deque[str] = deque(maxlen=max_lines)

    def emit(self, record: logging.LogRecord) -> None:
        """Store a formatted log record."""
        self.lines.append(self.format(record))


class TerminalUi:
    """Simple ANSI terminal dashboard for the debug SIP client."""

    def __init__(
        self,
        *,
        client_holder: dict[str, Any],
        api_holder: dict[str, DebugApiRuntime | None],
        args: argparse.Namespace,
        logs: RecentLogHandler,
    ) -> None:
        """Initialize dashboard state."""
        self._client_holder = client_holder
        self._api_holder = api_holder
        self._args = args
        self._logs = logs

    def render(self) -> None:
        """Render the current dashboard."""
        client = self._client_holder.get("client")
        api = self._api_holder.get("api")
        lines = [
            "\x1b[2J\x1b[H",
            "Dom.ru SIP Debug Client",
            "=" * 72,
            f"API host: {API_HOST}",
            f"API DNS override: {self._args.api_host_ip or '-'}",
            f"Account: {self._args.account_username or '<direct SIP credentials>'}",
            f"Auto-answer: {'on' if self._args.auto_answer else 'off'}",
            f"Auto-open: {'on' if self._args.auto_open else 'off'}",
            f"REST open: {'ready' if api else 'unavailable'}",
        ]
        if api:
            lines.extend(
                [
                    f"Place ID: {api.place_id}",
                    f"Access control ID: {api.access_control_id}",
                ]
            )
        lines.extend(
            [
                "",
            ]
        )

        if client is None:
            lines.extend(["SIP: initializing", ""])
        else:
            call_info = client.get_active_call_info() or {}
            lines.extend(
                [
                    f"SIP realm: {client.realm}",
                    f"SIP registrar: {client.server_addr[0]}:{client.server_addr[1]}",
                    f"SIP user: {client.username}",
                    f"Local bind: {client.local_ip}:{client.local_port}",
                    f"Mode: {client.registration_mode}",
                    f"Running: {client.is_running}",
                    f"Registered: {client.is_registered}",
                    f"Expires: {client.expires}s",
                    f"CSeq: {client.cseq}",
                    f"Call status: {client.call_status}",
                    f"Call-ID: {call_info.get('call_id', '-')}",
                    f"Caller: {call_info.get('from', '-')}",
                    "",
                ]
            )

        lines.extend(
            [
                "Commands",
                "  a answer   o open+hangup     h hangup   r reject",
                "  g register q quit            ? redraw",
                "",
                "Recent logs",
            ]
        )
        lines.extend(f"  {line}" for line in list(self._logs.lines)[-MAX_RECENT_LOGS:])
        lines.append("")
        lines.append("Press a command key.")
        print("\n".join(lines), end="", flush=True)


async def _answer_hangup_and_open(
    client: Any,
    api: DebugApiRuntime | None,
) -> str:
    """Answer/hang up the SIP call, then open the door through REST if possible."""
    parts = [f"answer+hangup -> {client.answer_and_hangup()}"]
    if api is None:
        parts.append("open_door -> skipped (no Dom.ru account API context)")
        return "; ".join(parts)

    try:
        await api.open_door()
    except Exception as exc:  # noqa: BLE001
        parts.append(f"open_door -> failed: {exc}")
    else:
        parts.append("open_door -> sent")
    return "; ".join(parts)


async def _run_command(  # noqa: PLR0911
    client: Any,
    api: DebugApiRuntime | None,
    command: str,
    stop_event: asyncio.Event,
) -> str:
    """Execute one debug command."""
    command = command.strip().lower()
    if command in {"quit", "exit", "q"}:
        stop_event.set()
        return "quit requested"
    if command in {"answer", "a"}:
        return f"answer -> {client.answer_call()}"
    if command in {"hangup", "h"}:
        return f"hangup -> {client.hangup_call()}"
    if command in {"reject", "r"}:
        return f"reject -> {client.reject_call()}"
    if command in {"register", "g"}:
        client.register_now(force=True)
        return "register -> sent"
    if command == "answer+hangup":
        return f"answer+hangup -> {client.answer_and_hangup()}"
    if command in {"open", "o", "open+hangup"}:
        return await _answer_hangup_and_open(client, api)
    if command in {"?", "redraw"}:
        return "redraw"
    return f"unknown command: {command}"


def _load_sip_module() -> ModuleType:
    """Load sip.py without importing Home Assistant package modules."""
    repo_root = Path(__file__).resolve().parents[1]
    module_path = repo_root / "custom_components" / "domru" / "sip.py"
    spec = importlib.util.spec_from_file_location("domru_sip_debug_core", module_path)
    if spec is None or spec.loader is None:
        msg = f"Cannot load SIP module from {module_path}"
        raise RuntimeError(msg)
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def _env_bool(name: str, *, default: bool = False) -> bool:
    """Read a boolean environment variable."""
    value = os.environ.get(name)
    if value is None:
        return default
    return value.strip().lower() in {"1", "true", "yes", "on"}


def _configure_logging(
    *,
    log_level: str,
    no_tui: bool,
    root_logger: logging.Logger | None = None,
) -> None:
    """Configure logging without corrupting the active TUI."""
    logger = root_logger or logging.getLogger()
    logger.setLevel(getattr(logging, str(log_level).upper(), logging.DEBUG))
    logger.handlers.clear()

    if no_tui:
        handler = logging.StreamHandler()
        handler.setFormatter(
            logging.Formatter("%(asctime)s %(levelname)s %(name)s: %(message)s")
        )
        logger.addHandler(handler)


def _build_parser() -> argparse.ArgumentParser:
    """Build CLI argument parser."""
    parser = argparse.ArgumentParser(
        description=(
            "Run the Dom.ru SIP client outside Home Assistant and print "
            "redacted SIP wire logs."
        )
    )
    parser.add_argument(
        "--realm",
        default=os.environ.get("DOMRU_SIP_REALM"),
        help="SIP realm/registrar host, or DOMRU_SIP_REALM.",
    )
    parser.add_argument(
        "--username",
        default=os.environ.get("DOMRU_SIP_USERNAME"),
        help="SIP username/login, or DOMRU_SIP_USERNAME.",
    )
    parser.add_argument(
        "--password",
        default=os.environ.get("DOMRU_SIP_PASSWORD"),
        help="SIP password, or DOMRU_SIP_PASSWORD.",
    )
    parser.add_argument(
        "--account-username",
        default=os.environ.get("DOMRU_ACCOUNT_USERNAME"),
        help=(
            "Normal Dom.ru account username/phone for automatic SIP credential "
            "fetching, or DOMRU_ACCOUNT_USERNAME."
        ),
    )
    parser.add_argument(
        "--account-password",
        default=os.environ.get("DOMRU_ACCOUNT_PASSWORD"),
        help=(
            "Normal Dom.ru account password for automatic SIP credential fetching, "
            "or DOMRU_ACCOUNT_PASSWORD."
        ),
    )
    parser.add_argument(
        "--installation-id",
        default=os.environ.get("DOMRU_INSTALLATION_ID"),
        help=(
            "Installation ID for the sipdevices endpoint. Defaults to a stable "
            "debug ID derived from account username."
        ),
    )
    parser.add_argument(
        "--place-id",
        default=os.environ.get("DOMRU_PLACE_ID"),
        help="Optional Dom.ru place ID. Defaults to the first place.",
    )
    parser.add_argument(
        "--access-control-id",
        default=os.environ.get("DOMRU_ACCESS_CONTROL_ID"),
        help="Optional Dom.ru access control ID. Defaults to the first device.",
    )
    parser.add_argument(
        "--api-host-ip",
        default=os.environ.get("DOMRU_API_HOST_IP"),
        help=(
            "Bypass Python DNS for myhome.proptech.ru by connecting to this IP "
            "while preserving HTTPS host/SNI, or DOMRU_API_HOST_IP."
        ),
    )
    parser.add_argument(
        "--sip-host-ip",
        default=os.environ.get("DOMRU_SIP_HOST_IP"),
        help=(
            "Bypass Python/asyncio UDP hostname sends for the SIP realm by using "
            "this registrar IP, or DOMRU_SIP_HOST_IP."
        ),
    )
    parser.add_argument(
        "--local-ip",
        default=os.environ.get("DOMRU_SIP_LOCAL_IP"),
        help="Local IP to bind. Defaults to auto-detection.",
    )
    parser.add_argument(
        "--local-port",
        type=int,
        default=int(os.environ.get("DOMRU_SIP_LOCAL_PORT", "5060")),
        help="Local UDP SIP port. Defaults to 5060.",
    )
    parser.add_argument(
        "--registration-mode",
        choices=["persistent", "on_demand"],
        default=os.environ.get("DOMRU_SIP_REGISTRATION_MODE", "persistent"),
        help="Registration mode. Defaults to persistent.",
    )
    parser.add_argument(
        "--auto-answer",
        action="store_true",
        default=_env_bool("DOMRU_SIP_AUTO_ANSWER"),
        help="Automatically answer an incoming call and hang up after ACK.",
    )
    parser.add_argument(
        "--auto-open",
        action="store_true",
        default=_env_bool("DOMRU_SIP_AUTO_OPEN"),
        help=(
            "Automatically answer an incoming call, hang up after ACK, and send "
            "the REST door-open action. Requires Dom.ru account credentials."
        ),
    )
    parser.add_argument(
        "--call-timeout",
        type=float,
        default=float(os.environ.get("DOMRU_SIP_CALL_TIMEOUT", "30")),
        help="Seconds before rejecting an unanswered call. Use 0 to disable.",
    )
    parser.add_argument(
        "--log-level",
        default=os.environ.get("DOMRU_SIP_LOG_LEVEL", "DEBUG"),
        help="Python log level. Defaults to DEBUG.",
    )
    parser.add_argument(
        "--no-tui",
        action="store_true",
        default=_env_bool("DOMRU_SIP_NO_TUI"),
        help="Disable the terminal dashboard and use line commands.",
    )
    return parser


def _validate_args(args: argparse.Namespace, parser: argparse.ArgumentParser) -> None:
    """Validate required connection arguments."""
    if args.auto_open and not (args.account_username and args.account_password):
        parser.error(
            "--auto-open requires Dom.ru account credentials "
            "(--account-username and --account-password) so the REST door-open "
            "action can be sent"
        )

    has_sip_credentials = args.realm and args.username and args.password
    if has_sip_credentials:
        return

    missing_account = [
        name
        for name in ("account_username", "account_password")
        if not getattr(args, name)
    ]
    if missing_account:
        parser.error(
            "provide either direct SIP credentials "
            "(--realm, --username, --password) or Dom.ru account credentials "
            "(--account-username, --account-password) to fetch SIP credentials "
            "automatically"
        )


def _hash1(password: str) -> str:
    """Build Dom.ru auth hash1."""
    digest = hashlib.sha1(password.encode("iso-8859-1")).digest()  # noqa: S324
    return base64.b64encode(digest).decode("utf-8")


def _hash2(username: str, password: str, timestamp: datetime) -> str:
    """Build Dom.ru auth hash2."""
    timestamp_str = timestamp.strftime("%Y%m%d%H%M%S")
    combined = (
        f"{HASH2_PREFIX}password{username}{password}"
        f"{timestamp_str}{HASH2_SECRET}"
    )
    return hashlib.md5(combined.encode("utf-8")).hexdigest()  # noqa: S324


def _installation_id(account_username: str, value: str | None) -> str:
    """Return an explicit or deterministic debug installation ID."""
    if value:
        return str(UUID(value))
    return str(uuid5(NAMESPACE_URL, f"domru-ha-debug-sip:{account_username}"))


def _dns_error_message(host: str) -> str:
    """Return an actionable DNS/network error message."""
    return (
        f"Could not resolve or reach DNS for {host}. This happens before Dom.ru "
        "authentication, so it is a local network/DNS issue rather than a SIP "
        "credential issue. If it works with VPN, run this client with VPN enabled "
        "or fix the DNS resolver used by this machine/container. You can also set "
        "HTTPS_PROXY/HTTP_PROXY; the debug client uses aiohttp trust_env=True."
    )


async def _request_json(
    session: Any,
    *,
    method: str,
    url: str,
    headers: dict[str, str],
    json_data: dict[str, Any] | None = None,
) -> Any:
    """Send an HTTP request and return JSON with a clear error on failure."""
    async with asyncio.timeout(20):
        response = await session.request(
            method=method,
            url=url,
            headers=headers,
            json=json_data,
        )
        try:
            payload = await response.json()
        except Exception as exc:
            text = await response.text()
            msg = f"{method} {url} returned non-JSON {response.status}: {text[:200]}"
            raise RuntimeError(msg) from exc

        if response.status not in {200, 201}:
            msg = f"{method} {url} failed with HTTP {response.status}: {payload}"
            raise RuntimeError(msg)
        return payload


async def _fetch_sip_credentials(  # noqa: PLR0912,PLR0915
    args: argparse.Namespace,
    logger: logging.Logger,
) -> DebugApiRuntime | None:
    """Fetch SIP credentials and keep an API runtime for door-open commands."""
    if not (args.account_username and args.account_password):
        return None

    import aiohttp  # noqa: PLC0415

    logger.info("Authenticating with Dom.ru account API")
    timestamp = datetime.now(UTC)
    auth_headers = {
        "Content-Type": "application/json; charset=UTF-8",
        "User-Agent": USER_AGENT,
    }
    auth_body = {
        "login": str(args.account_username),
        "timestamp": timestamp.strftime("%Y-%m-%dT%H:%M:%SZ"),
        "hash1": _hash1(args.account_password),
        "hash2": _hash2(args.account_username, args.account_password, timestamp),
    }

    try:
        session = None
        connector = None
        if args.api_host_ip:
            logger.info(
                "Using static API DNS override: %s -> %s",
                API_HOST,
                args.api_host_ip,
            )
            connector = aiohttp.TCPConnector(
                resolver=StaticHostResolver({API_HOST: args.api_host_ip}),
                use_dns_cache=False,
            )

        session = aiohttp.ClientSession(
            connector=connector,
            trust_env=True,
        )
        auth_payload = await _request_json(
            session,
            method="POST",
            url=urljoin(
                BASE_URL,
                f"auth/v2/auth/{args.account_username}/password",
            ),
            headers=auth_headers,
            json_data=auth_body,
        )
        access_token = auth_payload.get("accessToken")
        operator_id = auth_payload.get("operatorId")
        if not access_token or not operator_id:
            msg = "Dom.ru auth response did not include accessToken/operatorId"
            raise RuntimeError(msg)  # noqa: TRY301

        api_headers = {
            "Authorization": f"Bearer {access_token}",
            "Operator": str(operator_id),
            "User-Agent": USER_AGENT,
            "Content-Type": "application/json; charset=UTF-8",
            "Connection": "Keep-Alive",
            "Accept-Encoding": "gzip, deflate",
        }
        places_payload = await _request_json(
            session,
            method="GET",
            url=urljoin(BASE_URL, "rest/v1/subscriberplaces"),
            headers=api_headers,
        )
        places = (
            places_payload.get("data", [])
            if isinstance(places_payload, dict)
            else places_payload
        )
        if not places:
            msg = "Dom.ru account has no places"
            raise RuntimeError(msg)  # noqa: TRY301

        place_record = places[0] if isinstance(places, list) else places
        place = place_record.get("place", place_record)
        place_id = args.place_id or place.get("id")
        access_controls = place.get("accessControls", [])
        if not place_id or not access_controls:
            msg = "Dom.ru place has no access controls"
            raise RuntimeError(msg)  # noqa: TRY301

        access_control_id = args.access_control_id or access_controls[0].get("id")
        if not access_control_id:
            msg = "Could not determine Dom.ru access control ID"
            raise RuntimeError(msg)  # noqa: TRY301

        api_runtime = DebugApiRuntime(
            session=session,
            headers=api_headers,
            place_id=str(place_id),
            access_control_id=str(access_control_id),
        )

        if args.realm and args.username and args.password:
            logger.info(
                "Using provided SIP credentials; REST open-door context ready "
                "for place=%s access_control=%s",
                place_id,
                access_control_id,
            )
            return api_runtime

        install_id = _installation_id(args.account_username, args.installation_id)
        logger.info(
            "Requesting SIP credentials for place=%s access_control=%s "
            "installation_id=%s",
            place_id,
            access_control_id,
            install_id,
        )
        sip_payload = await _request_json(
            session,
            method="POST",
            url=urljoin(
                BASE_URL,
                f"rest/v1/places/{place_id}/accesscontrols/"
                f"{access_control_id}/sipdevices",
            ),
            headers=api_headers,
            json_data={"installationId": install_id},
        )
    except aiohttp.ClientConnectorDNSError as exc:
        if session:
            await session.close()
        raise RuntimeError(_dns_error_message("myhome.proptech.ru")) from exc
    except aiohttp.ClientConnectorError as exc:
        if session:
            await session.close()
        msg = (
            "Could not connect to Dom.ru API. If this only works with VPN, run "
            "the debug client while connected to VPN or check DNS/proxy/firewall "
            f"settings. Original error: {exc}"
        )
        raise RuntimeError(msg) from exc
    except Exception:
        if session:
            await session.close()
        raise

    sip_data = sip_payload.get("data", sip_payload)
    args.username = args.username or sip_data.get("login")
    args.password = args.password or sip_data.get("password")
    args.realm = args.realm or sip_data.get("realm")

    if not (args.username and args.password and args.realm):
        msg = f"SIP credential response was incomplete: {sip_data}"
        raise RuntimeError(msg)
    logger.info("Fetched SIP credentials for %s@%s", args.username, args.realm)
    return api_runtime


async def _command_loop(
    client: Any,
    api: DebugApiRuntime | None,
    stop_event: asyncio.Event,
    ui: TerminalUi | None,
    logger: logging.Logger,
) -> None:
    """Read simple commands from stdin."""
    if ui and os.name == "nt" and sys.stdin.isatty():
        import msvcrt  # noqa: PLC0415

        ui.render()
        while not stop_event.is_set():
            if msvcrt.kbhit():
                command = msvcrt.getwch()
                result = await _run_command(client, api, command, stop_event)
                logger.info("COMMAND %s", result)
                ui.render()
            await asyncio.sleep(0.1)
        return

    print("Commands: answer, open, hangup, reject, register, quit", flush=True)
    while not stop_event.is_set():
        if ui:
            ui.render()
        line = await asyncio.to_thread(sys.stdin.readline)
        if not line:
            await asyncio.sleep(0.5)
            continue

        result = await _run_command(client, api, line, stop_event)
        logger.info("COMMAND %s", result)
        if not ui:
            print(result, flush=True)


async def _auto_open_call(
    client: Any,
    api: DebugApiRuntime | None,
    logger: logging.Logger,
) -> None:
    """Run the automatic SIP answer plus REST open flow."""
    result = await _answer_hangup_and_open(client, api)
    logger.info("AUTO %s", result)


async def _async_main(args: argparse.Namespace) -> int:
    """Run the debug SIP client."""
    sip_module = _load_sip_module()
    logger = logging.getLogger("domru.sip_debug_client")
    recent_logs = RecentLogHandler()
    recent_logs.setFormatter(logging.Formatter("%(levelname)s %(name)s: %(message)s"))
    logging.getLogger().addHandler(recent_logs)

    api_runtime = await _fetch_sip_credentials(args, logger)
    stop_event = asyncio.Event()
    client_holder: dict[str, Any] = {}
    api_holder: dict[str, DebugApiRuntime | None] = {"api": api_runtime}
    ui_holder: dict[str, TerminalUi | None] = {"ui": None}
    auto_tasks: set[asyncio.Task[None]] = set()

    def on_event(data: dict[str, Any]) -> None:
        event = data.get("event", "unknown")
        safe_data = {
            key: value
            for key, value in data.items()
            if key not in {"password", "authorization"}
        }
        logger.info("EVENT %s %s", event, safe_data)
        if event == "incoming_call":
            if args.auto_open:
                logger.info("Auto-opening incoming call")
                task = asyncio.create_task(
                    _auto_open_call(client_holder["client"], api_runtime, logger)
                )
                auto_tasks.add(task)
                task.add_done_callback(auto_tasks.discard)
            elif args.auto_answer:
                logger.info("Auto-answering incoming call")
                client_holder["client"].answer_and_hangup()
        if ui_holder["ui"]:
            ui_holder["ui"].render()

    client = sip_module.DomruSipClient(
        realm=args.realm,
        username=args.username,
        password=args.password,
        local_ip=args.local_ip or None,
        local_port=args.local_port,
        on_call_callback=on_event,
        registration_mode=args.registration_mode,
        call_timeout=args.call_timeout,
        server_ip=args.sip_host_ip or None,
    )
    client_holder["client"] = client
    ui_holder["ui"] = None if args.no_tui else TerminalUi(
        client_holder=client_holder,
        api_holder=api_holder,
        args=args,
        logs=recent_logs,
    )

    loop = asyncio.get_running_loop()
    for sig_name in ("SIGINT", "SIGTERM"):
        sig = getattr(signal, sig_name, None)
        if sig is None:
            continue
        with suppress(NotImplementedError, RuntimeError):
            loop.add_signal_handler(sig, stop_event.set)

    try:
        await client.start()
        logger.info(
            "Debug SIP client started for %s@%s on %s:%d",
            args.username,
            args.realm,
            client.local_ip,
            client.local_port,
        )
        if ui_holder["ui"]:
            ui_holder["ui"].render()

        await _command_loop(client, api_runtime, stop_event, ui_holder["ui"], logger)
    finally:
        await client.stop()
        if auto_tasks:
            await asyncio.gather(*auto_tasks, return_exceptions=True)
        if api_runtime:
            await api_runtime.close()
        logger.info("Debug SIP client stopped")

    return 0


def main() -> int:
    """CLI entrypoint."""
    parser = _build_parser()
    args = parser.parse_args()
    _validate_args(args, parser)

    _configure_logging(log_level=args.log_level, no_tui=args.no_tui)
    return asyncio.run(_async_main(args))


if __name__ == "__main__":
    raise SystemExit(main())
