"""Helpers shared by SIP-backed Home Assistant entities."""

from __future__ import annotations

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
