# ruff: noqa: D102,D107,EM102,TRY003,PT009
"""Tests for Home Assistant SIP entity helper behavior."""

from __future__ import annotations

import asyncio
import importlib.util
import sys
import unittest
from pathlib import Path

SIP_ENTITIES_MODULE_PATH = Path("custom_components/domru/sip_entities.py")
spec = importlib.util.spec_from_file_location(
    "domru_sip_entities_for_tests",
    SIP_ENTITIES_MODULE_PATH,
)
if spec is None or spec.loader is None:
    raise RuntimeError(f"Cannot load {SIP_ENTITIES_MODULE_PATH}")
sip_entities = importlib.util.module_from_spec(spec)
sys.modules[spec.name] = sip_entities
spec.loader.exec_module(sip_entities)


class FakeSipClient:
    """Fake SIP client used by entity helper tests."""

    def __init__(self, status: str = "idle") -> None:
        self.call_status = status
        self.dismissed = False
        self.answered_and_hung_up = False
        self.registered_now = False
        self.registered_for_incoming_call = False

    def hangup_call(self) -> bool:
        self.dismissed = True
        return True

    def register_now(self) -> None:
        self.registered_now = True

    def register_for_incoming_call(self) -> None:
        self.registered_for_incoming_call = True

    def answer_and_hangup(self) -> bool:
        self.answered_and_hung_up = True
        return True

    def get_active_call_info(self) -> dict[str, str]:
        return {
            "from": 'From: "Door Panel" <sip:000@example.test>',
            "call_id": "call-1",
            "remote_contact_uri": "sip:door@example.test",
            "status": self.call_status,
        }


class SipEntityHelperTests(unittest.TestCase):
    """SIP helper behavior for HA platform wrappers."""

    def test_call_and_door_buttons_are_control_entities(self) -> None:
        source = Path("custom_components/domru/button.py").read_text()

        self.assertNotIn("entity_category=EntityCategory.CONFIG", source)

    def test_button_keys_are_open_and_dismiss_only(self) -> None:
        self.assertEqual(
            sip_entities.SIP_BUTTON_KEYS,
            ("open_door", "dismiss_call"),
        )

    def test_call_status_is_raw_machine_readable_value(self) -> None:
        self.assertEqual(
            sip_entities.call_status_value(FakeSipClient("ringing")),
            "ringing",
        )
        self.assertEqual(sip_entities.call_status_value(None), "disabled")

    def test_call_status_attributes_include_calling_flag_and_caller(self) -> None:
        attrs = sip_entities.call_status_attributes(FakeSipClient("ringing"))

        self.assertEqual(attrs["is_calling"], True)
        self.assertEqual(attrs["caller"], "Door Panel")
        self.assertEqual(attrs["call_id"], "call-1")

    def test_dismiss_call_uses_sip_hangup_or_reject_flow(self) -> None:
        client = FakeSipClient("ringing")

        self.assertTrue(sip_entities.dismiss_call(client))
        self.assertTrue(client.dismissed)
        self.assertFalse(sip_entities.dismiss_call(None))

    def test_answer_and_hangup_when_ready_uses_active_call_immediately(self) -> None:
        client = FakeSipClient("ringing")

        result = asyncio.run(sip_entities.async_answer_and_hangup_when_ready(client))

        self.assertTrue(result)
        self.assertTrue(client.answered_and_hung_up)
        self.assertFalse(client.registered_now)

    def test_answer_and_hangup_when_ready_registers_and_waits_for_fcm_invite(
        self,
    ) -> None:
        client = FakeSipClient("idle")

        async def make_call_ring() -> None:
            await asyncio.sleep(0)
            client.call_status = "ringing"

        async def run() -> bool:
            task = asyncio.create_task(make_call_ring())
            try:
                return await sip_entities.async_answer_and_hangup_when_ready(
                    client,
                    wait_timeout=0.2,
                    poll_interval=0,
                )
            finally:
                await task

        result = asyncio.run(run())

        self.assertTrue(result)
        self.assertFalse(client.registered_now)
        self.assertTrue(client.registered_for_incoming_call)
        self.assertTrue(client.answered_and_hung_up)


if __name__ == "__main__":
    unittest.main()
