# ruff: noqa: D102,D107,EM102,TRY003,S106,S324,SLF001,PT009,S603
"""Tests for the pure Python Dom.ru SIP client."""

from __future__ import annotations

import asyncio
import hashlib
import importlib.util
import logging
import subprocess
import sys
import unittest
from pathlib import Path

SIP_MODULE_PATH = Path("custom_components/domru/sip.py")
spec = importlib.util.spec_from_file_location("domru_sip_for_tests", SIP_MODULE_PATH)
if spec is None or spec.loader is None:
    raise RuntimeError(f"Cannot load {SIP_MODULE_PATH}")
sip_module = importlib.util.module_from_spec(spec)
sys.modules[spec.name] = sip_module
spec.loader.exec_module(sip_module)

DigestAuth = sip_module.DigestAuth
DomruSipClient = sip_module.DomruSipClient
SipMessage = sip_module.SipMessage

DEBUG_CLIENT_MODULE_PATH = Path("dev/sip_debug_client.py")
debug_spec = importlib.util.spec_from_file_location(
    "sip_debug_client_for_tests",
    DEBUG_CLIENT_MODULE_PATH,
)
if debug_spec is None or debug_spec.loader is None:
    raise RuntimeError(f"Cannot load {DEBUG_CLIENT_MODULE_PATH}")
debug_client_module = importlib.util.module_from_spec(debug_spec)
sys.modules[debug_spec.name] = debug_client_module
debug_spec.loader.exec_module(debug_client_module)


INVITE = (
    "INVITE sip:user@5676.spb.domofon.domru.ru SIP/2.0\r\n"
    "Via: SIP/2.0/UDP 158.160.67.92:5060;branch=z9hG4bKproxy\r\n"
    "Via: SIP/2.0/UDP 51.250.66.20:11000;branch=z9hG4bKdoor\r\n"
    'From: "Door" <sip:000@5676.spb.domofon.domru.ru>;tag=remote-tag\r\n'
    "To: <sip:user@5676.spb.domofon.domru.ru>\r\n"
    "Call-ID: call-1\r\n"
    "CSeq: 42 INVITE\r\n"
    "Contact: <sip:mod_sofia@51.250.66.20:11000;alias=10.65.8.41~11000~1>\r\n"
    "Record-Route: <sip:158.160.67.92;lr=on;ftag=remote-tag>\r\n"
    "Content-Type: application/sdp\r\n"
    "Content-Length: 129\r\n"
    "\r\n"
    "v=0\r\n"
    "o=FreeSWITCH 1 2 IN IP4 51.250.66.20\r\n"
    "s=FreeSWITCH\r\n"
    "c=IN IP4 51.250.66.20\r\n"
    "t=0 0\r\n"
    "m=audio 16594 RTP/AVP 0 8 101\r\n"
)


ACK = (
    "ACK sip:user@5676.spb.domofon.domru.ru SIP/2.0\r\n"
    "Via: SIP/2.0/UDP 158.160.67.92:5060;branch=z9hG4bKack\r\n"
    'From: "Door" <sip:000@5676.spb.domofon.domru.ru>;tag=remote-tag\r\n'
    "To: <sip:user@5676.spb.domofon.domru.ru>;tag=local-tag\r\n"
    "Call-ID: call-1\r\n"
    "CSeq: 42 ACK\r\n"
    "Content-Length: 0\r\n\r\n"
)


CANCEL = (
    "CANCEL sip:user@5676.spb.domofon.domru.ru SIP/2.0\r\n"
    "Via: SIP/2.0/UDP 158.160.67.92:5060;branch=z9hG4bKproxy\r\n"
    'From: "Door" <sip:000@5676.spb.domofon.domru.ru>;tag=remote-tag\r\n'
    "To: <sip:user@5676.spb.domofon.domru.ru>\r\n"
    "Call-ID: call-1\r\n"
    "CSeq: 42 CANCEL\r\n"
    "Content-Length: 0\r\n\r\n"
)


REMOTE_BYE = (
    "BYE sip:user@5676.spb.domofon.domru.ru SIP/2.0\r\n"
    "Via: SIP/2.0/UDP 158.160.67.92:5060;branch=z9hG4bKbye\r\n"
    'From: "Door" <sip:000@5676.spb.domofon.domru.ru>;tag=remote-tag\r\n'
    "To: <sip:user@5676.spb.domofon.domru.ru>;tag=local-tag\r\n"
    "Call-ID: call-1\r\n"
    "CSeq: 43 BYE\r\n"
    "Content-Length: 0\r\n\r\n"
)


class FakeTransport:
    """Capture datagrams sent by the SIP client."""

    def __init__(self) -> None:
        self.sent: list[tuple[str, tuple[str, int]]] = []
        self.closed = False

    def sendto(self, data: bytes, addr: tuple[str, int]) -> None:
        self.sent.append((data.decode("utf-8"), addr))

    def close(self) -> None:
        self.closed = True


class SipTestCase(unittest.TestCase):
    """Base class with a deterministic event loop."""

    def setUp(self) -> None:
        self.loop = asyncio.new_event_loop()
        asyncio.set_event_loop(self.loop)

    def tearDown(self) -> None:
        self.loop.close()
        asyncio.set_event_loop(None)

    def make_client(self) -> tuple[DomruSipClient, FakeTransport]:
        client = DomruSipClient(
            realm="5676.spb.domofon.domru.ru",
            username="user",
            password="pass",
            local_ip="192.0.2.10",
            local_port=5060,
            on_call_callback=lambda _data: None,
        )
        transport = FakeTransport()
        client._transport = transport
        client._running = True
        return client, transport


class SipMessageTests(unittest.TestCase):
    """SIP parser and builder behavior."""

    def test_parser_preserves_repeated_via_headers_and_body(self) -> None:
        msg = SipMessage.parse(INVITE)

        self.assertEqual(
            msg.start_line,
            "INVITE sip:user@5676.spb.domofon.domru.ru SIP/2.0",
        )
        self.assertEqual(len(msg.header_values("Via")), 2)
        self.assertEqual(msg.first_header("Call-ID"), "call-1")
        self.assertEqual(msg.cseq_method, "INVITE")
        self.assertIn("m=audio 16594", msg.body)

    def test_builder_recalculates_content_length(self) -> None:
        msg = SipMessage(
            start_line="SIP/2.0 200 OK",
            headers=[("Via", "SIP/2.0/UDP example;branch=z9hG4bK")],
            body="abc",
        )

        text = msg.to_text()

        self.assertIn("Content-Length: 3\r\n\r\nabc", text)

    def test_redacted_text_hides_authentication_material(self) -> None:
        msg = SipMessage.parse(
            "REGISTER sip:example.com SIP/2.0\r\n"
            'Authorization: Digest username="user", nonce="secret", '
            'response="hidden"\r\n'
            'WWW-Authenticate: Digest realm="example.com", nonce="secret"\r\n'
            "Content-Length: 0\r\n\r\n"
        )

        redacted = msg.to_redacted_text()

        self.assertIn("Authorization: <redacted>", redacted)
        self.assertIn("WWW-Authenticate: <redacted>", redacted)
        self.assertNotIn("secret", redacted)
        self.assertNotIn("hidden", redacted)


class DigestAuthTests(unittest.TestCase):
    """Digest authentication behavior."""

    def test_digest_auth_builds_expected_response_without_qop(self) -> None:
        challenge = DigestAuth.from_header(
            'Digest realm="example.com", nonce="abc123", algorithm=MD5'
        )

        header = challenge.build_authorization(
            username="alice",
            password="secret",
            method="REGISTER",
            uri="sip:example.com",
        )

        ha1 = hashlib.md5(b"alice:example.com:secret").hexdigest()
        ha2 = hashlib.md5(b"REGISTER:sip:example.com").hexdigest()
        expected = hashlib.md5(f"{ha1}:abc123:{ha2}".encode()).hexdigest()
        self.assertIn(f'response="{expected}"', header)
        self.assertIn('username="alice"', header)
        self.assertIn('uri="sip:example.com"', header)


class DomruSipClientTests(SipTestCase):
    """SIP call state machine behavior."""

    def test_invite_sends_trying_and_enters_ringing(self) -> None:
        client, transport = self.make_client()

        client.handle_message(INVITE.encode(), ("158.160.67.92", 5060))

        self.assertEqual(client.call_status, "ringing")
        sent, addr = transport.sent[-1]
        self.assertEqual(addr, ("158.160.67.92", 5060))
        self.assertTrue(sent.startswith("SIP/2.0 100 Trying\r\n"))
        self.assertEqual(sent.count("Via:"), 2)
        to_line = next(line for line in sent.splitlines() if line.startswith("To:"))
        self.assertNotIn(";tag=", to_line)

    def test_answer_sends_sdp_ok_with_stable_to_tag(self) -> None:
        client, transport = self.make_client()
        client.handle_message(INVITE.encode(), ("158.160.67.92", 5060))

        self.assertTrue(client.answer_call())

        self.assertEqual(client.call_status, "answered")
        sent = transport.sent[-1][0]
        self.assertTrue(sent.startswith("SIP/2.0 200 OK\r\n"))
        self.assertIn("Content-Type: application/sdp\r\n", sent)
        self.assertIn("m=audio ", sent)
        self.assertIn("a=rtpmap:101 telephone-event/8000", sent)
        self.assertRegex(sent, r"To: <sip:user@5676.*>;tag=[a-f0-9]+")
        parsed = SipMessage.parse(sent)
        self.assertEqual(
            int(parsed.first_header("Content-Length")),
            len(parsed.body.encode("utf-8")),
        )

    def test_answer_and_hangup_sends_bye_after_ack_and_clears_on_ok(self) -> None:
        client, transport = self.make_client()
        client.handle_message(INVITE.encode(), ("158.160.67.92", 5060))

        self.assertTrue(client.answer_and_hangup())
        self.assertEqual(client.call_status, "answered")

        client.handle_message(ACK.encode(), ("158.160.67.92", 5060))

        self.assertEqual(client.call_status, "ending")
        bye = transport.sent[-1][0]
        self.assertTrue(
            bye.startswith(
                "BYE sip:mod_sofia@51.250.66.20:11000;"
                "alias=10.65.8.41~11000~1 SIP/2.0\r\n"
            )
        )
        self.assertIn("Route: <sip:158.160.67.92;lr=on;ftag=remote-tag>", bye)
        self.assertIn(
            'To: "Door" <sip:000@5676.spb.domofon.domru.ru>;tag=remote-tag',
            bye,
        )
        cseq = SipMessage.parse(bye).first_header("CSeq")
        ok = (
            "SIP/2.0 200 OK\r\n"
            f"Via: SIP/2.0/UDP 192.0.2.10:5060;branch=z9hG4bK\r\n"
            "From: <sip:user@5676.spb.domofon.domru.ru>;tag=local\r\n"
            'To: "Door" <sip:000@5676.spb.domofon.domru.ru>;tag=remote-tag\r\n'
            "Call-ID: call-1\r\n"
            f"CSeq: {cseq}\r\n"
            "Content-Length: 0\r\n\r\n"
        )

        client.handle_message(ok.encode(), ("158.160.67.92", 5060))

        self.assertEqual(client.call_status, "idle")
        self.assertIsNone(client.get_active_call_info())

    def test_cancel_sends_ok_and_request_terminated(self) -> None:
        client, transport = self.make_client()
        client.handle_message(INVITE.encode(), ("158.160.67.92", 5060))
        transport.sent.clear()

        client.handle_message(CANCEL.encode(), ("158.160.67.92", 5060))

        self.assertEqual(client.call_status, "idle")
        self.assertEqual(len(transport.sent), 2)
        self.assertTrue(transport.sent[0][0].startswith("SIP/2.0 200 OK\r\n"))
        self.assertTrue(
            transport.sent[1][0].startswith("SIP/2.0 487 Request Terminated\r\n")
        )

    def test_remote_bye_is_acknowledged_and_clears_call(self) -> None:
        client, transport = self.make_client()
        client.handle_message(INVITE.encode(), ("158.160.67.92", 5060))
        client.answer_call()
        client.handle_message(ACK.encode(), ("158.160.67.92", 5060))
        transport.sent.clear()

        client.handle_message(REMOTE_BYE.encode(), ("158.160.67.92", 5060))

        self.assertEqual(client.call_status, "idle")
        self.assertTrue(transport.sent[-1][0].startswith("SIP/2.0 200 OK\r\n"))

    def test_registration_handles_401_then_authenticated_register(self) -> None:
        client, transport = self.make_client()

        client.register_now()
        self.assertTrue(transport.sent[-1][0].startswith("REGISTER "))

        unauthorized = (
            "SIP/2.0 401 Unauthorized\r\n"
            "Via: SIP/2.0/UDP 192.0.2.10:5060;branch=z9hG4bK\r\n"
            "From: <sip:user@5676.spb.domofon.domru.ru>;tag=reg\r\n"
            "To: <sip:user@5676.spb.domofon.domru.ru>;tag=server\r\n"
            "Call-ID: reg-call\r\n"
            "CSeq: 1 REGISTER\r\n"
            'WWW-Authenticate: Digest realm="5676.spb.domofon.domru.ru", '
            'nonce="nonce-1"\r\n'
            "Content-Length: 0\r\n\r\n"
        )

        client.handle_message(unauthorized.encode(), ("158.160.67.92", 5060))

        authed_register = transport.sent[-1][0]
        self.assertIn("Authorization: Digest ", authed_register)
        self.assertIn('username="user"', authed_register)
        self.assertIn('nonce="nonce-1"', authed_register)

        ok = (
            "SIP/2.0 200 OK\r\n"
            "Via: SIP/2.0/UDP 192.0.2.10:5060;branch=z9hG4bK\r\n"
            "From: <sip:user@5676.spb.domofon.domru.ru>;tag=reg\r\n"
            "To: <sip:user@5676.spb.domofon.domru.ru>;tag=server\r\n"
            "Call-ID: reg-call\r\n"
            "CSeq: 2 REGISTER\r\n"
            "Contact: <sip:user@203.0.113.10:5060;transport=udp>;expires=30\r\n"
            "Content-Length: 0\r\n\r\n"
        )

        client.handle_message(ok.encode(), ("158.160.67.92", 5060))

        self.assertTrue(client.is_registered)
        self.assertEqual(client.expires, 30)

    def test_registration_uses_configured_numeric_server_ip(self) -> None:
        client = DomruSipClient(
            realm="5676.spb.domofon.domru.ru",
            username="user",
            password="pass",
            local_ip="192.0.2.10",
            local_port=5060,
            server_ip="203.0.113.50",
        )
        transport = FakeTransport()
        client._transport = transport
        client._running = True

        client.register_now()

        self.assertEqual(transport.sent[-1][1], ("203.0.113.50", 5060))

    def test_register_defaults_to_android_observed_30_second_expiry(self) -> None:
        client, transport = self.make_client()

        client.register_now()

        register = transport.sent[-1][0]
        self.assertIn("Expires: 30\r\n", register)

    def test_register_logs_attempt_and_success_diagnostics(self) -> None:
        client, _transport = self.make_client()

        with self.assertLogs("domru_sip_for_tests", level="INFO") as logs:
            client.register_now()

        self.assertIn("Sending SIP REGISTER", "\n".join(logs.output))
        self.assertIsNotNone(client.last_register_at)

        ok = (
            "SIP/2.0 200 OK\r\n"
            "Via: SIP/2.0/UDP 192.0.2.10:5060;branch=z9hG4bK\r\n"
            "From: <sip:user@5676.spb.domofon.domru.ru>;tag=reg\r\n"
            "To: <sip:user@5676.spb.domofon.domru.ru>;tag=server\r\n"
            "Call-ID: reg-call\r\n"
            "CSeq: 1 REGISTER\r\n"
            "Contact: <sip:user@203.0.113.10:5060;transport=udp>;expires=30\r\n"
            "Content-Length: 0\r\n\r\n"
        )

        with self.assertLogs("domru_sip_for_tests", level="INFO") as logs:
            client.handle_message(ok.encode(), ("158.160.67.92", 5060))

        self.assertIn("SIP registration succeeded", "\n".join(logs.output))
        self.assertIsNotNone(client.last_registered_at)
        self.assertIsNone(client.last_error)

    def test_register_failure_records_last_error(self) -> None:
        client, _transport = self.make_client()
        client.register_now()
        forbidden = (
            "SIP/2.0 403 Forbidden\r\n"
            "Via: SIP/2.0/UDP 192.0.2.10:5060;branch=z9hG4bK\r\n"
            "From: <sip:user@5676.spb.domofon.domru.ru>;tag=reg\r\n"
            "To: <sip:user@5676.spb.domofon.domru.ru>;tag=server\r\n"
            "Call-ID: reg-call\r\n"
            "CSeq: 1 REGISTER\r\n"
            "Content-Length: 0\r\n\r\n"
        )

        with self.assertLogs("domru_sip_for_tests", level="ERROR") as logs:
            client.handle_message(forbidden.encode(), ("158.160.67.92", 5060))

        self.assertIn("SIP registration rejected", "\n".join(logs.output))
        self.assertEqual(client.last_error, "registration forbidden")

    def test_invite_logs_incoming_call_diagnostics(self) -> None:
        client, _transport = self.make_client()

        with self.assertLogs("domru_sip_for_tests", level="INFO") as logs:
            client.handle_message(INVITE.encode(), ("158.160.67.92", 5060))

        self.assertIn("Incoming SIP INVITE", "\n".join(logs.output))
        self.assertEqual(client.last_event, "incoming_call")


class DebugClientTests(unittest.TestCase):
    """Standalone debug client smoke tests."""

    class FakeDebugSipClient:
        """Minimal SIP client used by debug command tests."""

        def __init__(self) -> None:
            self.answered_and_hung_up = False

        def answer_and_hangup(self) -> bool:
            self.answered_and_hung_up = True
            return True

    class FakeDebugApi:
        """Minimal API runtime used by debug command tests."""

        def __init__(self) -> None:
            self.opened = False

        async def open_door(self) -> dict[str, str]:
            self.opened = True
            return {"result": "ok"}

    class FakeApiResponse:
        """HTTP response stub for DebugApiRuntime tests."""

        status = 200

        async def json(self) -> dict[str, dict[str, str]]:
            return {"data": {"result": "ok"}}

        async def text(self) -> str:
            return ""

    class FakeApiSession:
        """HTTP session stub for DebugApiRuntime tests."""

        def __init__(self) -> None:
            self.requests: list[dict[str, object]] = []
            self.closed = False

        async def request(
            self,
            *,
            method: str,
            url: str,
            headers: dict[str, str],
            json: dict[str, str] | None = None,
        ) -> DebugClientTests.FakeApiResponse:
            self.requests.append(
                {
                    "method": method,
                    "url": url,
                    "headers": headers,
                    "json": json,
                }
            )
            return DebugClientTests.FakeApiResponse()

        async def close(self) -> None:
            self.closed = True

    def test_debug_client_help_lists_required_options(self) -> None:
        script = Path("dev/sip_debug_client.py")

        result = subprocess.run(
            [sys.executable, str(script), "--help"],
            check=False,
            capture_output=True,
            text=True,
        )

        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("--realm", result.stdout)
        self.assertIn("--username", result.stdout)
        self.assertIn("--password", result.stdout)
        self.assertIn("--account-username", result.stdout)
        self.assertIn("--account-password", result.stdout)
        self.assertIn("--installation-id", result.stdout)
        self.assertIn("--api-host-ip", result.stdout)
        self.assertIn("--sip-host-ip", result.stdout)
        self.assertIn("--no-tui", result.stdout)
        self.assertIn("--auto-answer", result.stdout)
        self.assertIn("--auto-open", result.stdout)

    def test_open_command_answers_hangs_up_and_opens_via_rest(self) -> None:
        async def run() -> tuple[
            DebugClientTests.FakeDebugSipClient,
            DebugClientTests.FakeDebugApi,
            str,
        ]:
            client = DebugClientTests.FakeDebugSipClient()
            api = DebugClientTests.FakeDebugApi()
            result = await debug_client_module._run_command(
                client,
                api,
                "o",
                asyncio.Event(),
            )
            return client, api, result

        client, api, result = asyncio.run(run())

        self.assertTrue(client.answered_and_hung_up)
        self.assertTrue(api.opened)
        self.assertIn("answer+hangup -> True", result)
        self.assertIn("open_door -> sent", result)

    def test_open_command_reports_when_rest_context_is_missing(self) -> None:
        async def run() -> tuple[DebugClientTests.FakeDebugSipClient, str]:
            client = DebugClientTests.FakeDebugSipClient()
            result = await debug_client_module._run_command(
                client,
                None,
                "o",
                asyncio.Event(),
            )
            return client, result

        client, result = asyncio.run(run())

        self.assertTrue(client.answered_and_hung_up)
        self.assertIn("open_door -> skipped", result)

    def test_debug_api_runtime_posts_access_control_open_action(self) -> None:
        async def run() -> DebugClientTests.FakeApiSession:
            session = DebugClientTests.FakeApiSession()
            api = debug_client_module.DebugApiRuntime(
                session=session,
                headers={"Authorization": "Bearer token"},
                place_id="place-1",
                access_control_id="door-1",
            )

            result = await api.open_door()

            self.assertEqual(result, {"data": {"result": "ok"}})
            return session

        session = asyncio.run(run())
        request = session.requests[0]

        self.assertEqual(request["method"], "POST")
        self.assertTrue(str(request["url"]).endswith("/actions"))
        self.assertIn("/places/place-1/accesscontrols/door-1/", str(request["url"]))
        self.assertEqual(request["json"], {"name": "accessControlOpen"})

    def test_dns_error_message_points_to_network_dns_or_vpn(self) -> None:
        message = debug_client_module._dns_error_message("myhome.proptech.ru")

        self.assertIn("myhome.proptech.ru", message)
        self.assertIn("DNS", message)
        self.assertIn("VPN", message)

    def test_static_resolver_overrides_api_host(self) -> None:
        async def resolve() -> list[dict[str, object]]:
            resolver = debug_client_module.StaticHostResolver(
                {"myhome.proptech.ru": "91.221.164.89"}
            )
            return await resolver.resolve("myhome.proptech.ru", 443)

        result = asyncio.run(resolve())

        self.assertEqual(result[0]["hostname"], "myhome.proptech.ru")
        self.assertEqual(result[0]["host"], "91.221.164.89")
        self.assertEqual(result[0]["port"], 443)

    def test_tui_logging_does_not_add_console_stream_handler(self) -> None:
        logger = logging.getLogger("domru-test-tui-logging")
        logger.handlers.clear()
        logger.propagate = False

        debug_client_module._configure_logging(
            log_level="DEBUG",
            no_tui=False,
            root_logger=logger,
        )

        self.assertFalse(
            any(
                isinstance(handler, logging.StreamHandler)
                for handler in logger.handlers
            )
        )


if __name__ == "__main__":
    unittest.main()
