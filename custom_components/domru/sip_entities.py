"""Helpers shared by SIP-backed Home Assistant entities."""

from __future__ import annotations

import asyncio
import re
from typing import Any

SIP_BUTTON_KEYS = ("open_door", "dismiss_call")
CALL_STATUS_DISABLED = "disabled"
CALL_STATUS_RINGING = "ringing"


def call_status_value(sip_client: Any | None) -> str:
    """Return a machine-readable call status for the HA sensor."""
    if not sip_client:
        return CALL_STATUS_DISABLED
    return str(sip_client.call_status)


def call_status_attributes(sip_client: Any | None) -> dict[str, Any]:
    """Return attributes for the live SIP call status sensor."""
    status = call_status_value(sip_client)
    attrs: dict[str, Any] = {
        "is_calling": status == CALL_STATUS_RINGING,
    }
    if not sip_client:
        return attrs

    call_info = sip_client.get_active_call_info()
    if not call_info:
        return attrs

    from_header = call_info.get("from", "")
    caller_match = re.search(r'"([^"]+)"', from_header)
    attrs.update(
        {
            "caller": caller_match.group(1) if caller_match else "Unknown",
            "call_id": call_info.get("call_id", ""),
            "from_header": from_header,
            "remote_contact_uri": call_info.get("remote_contact_uri", ""),
        }
    )
    return attrs


def dismiss_call(sip_client: Any | None) -> bool:
    """Dismiss the active SIP call without opening the door."""
    if not sip_client:
        return False
    return bool(sip_client.hangup_call())


async def async_answer_and_hangup_when_ready(
    sip_client: Any | None,
    *,
    wait_timeout: float = 3.0,
    poll_interval: float = 0.1,
) -> bool:
    """Answer and hang up, waiting briefly for an FCM-triggered SIP INVITE."""
    if not sip_client:
        return False

    if str(sip_client.call_status) != "idle":
        return bool(sip_client.answer_and_hangup())

    register_for_incoming_call = getattr(sip_client, "register_for_incoming_call", None)
    if callable(register_for_incoming_call):
        register_for_incoming_call()
    else:
        register_now = getattr(sip_client, "register_now", None)
        if callable(register_now):
            register_now()

    loop = asyncio.get_running_loop()
    deadline = loop.time() + wait_timeout
    while loop.time() < deadline:
        await asyncio.sleep(poll_interval)
        if str(sip_client.call_status) != "idle":
            return bool(sip_client.answer_and_hangup())

    return bool(sip_client.answer_and_hangup())
