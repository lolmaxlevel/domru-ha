"""Diagnostics support for Dom.ru Smart Intercom."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from homeassistant.core import HomeAssistant

    from .data import DomruConfigEntry


async def async_get_config_entry_diagnostics(
    hass: HomeAssistant,  # noqa: ARG001
    entry: DomruConfigEntry,
) -> dict[str, Any]:
    """Return diagnostics for a config entry."""
    data = entry.runtime_data

    diagnostics = {
        "config_entry": {
            "entry_id": entry.entry_id,
            "version": entry.version,
            "options": dict(entry.options),
        },
        "coordinator": {
            "last_update_success": data.coordinator.last_update_success,
            "data_available": bool(data.coordinator.data),
        },
        "sip": {
            "enabled": data.sip_client is not None,
        },
    }

    if data.sip_client:
        diagnostics["sip"].update(
            {
                "running": data.sip_client.is_running,
                "local_ip": data.sip_client.local_ip,
                "local_port": data.sip_client.local_port,
                "realm": data.sip_client.realm,
                "username": data.sip_client.username,
                "expires": data.sip_client.expires,
                "cseq": data.sip_client.cseq,
            }
        )

    if data.coordinator.data:
        diagnostics["data"] = {
            "places": len(data.coordinator.data.get("places", [])),
            "access_controls": len(data.coordinator.data.get("access_controls", [])),
            "cameras": len(data.coordinator.data.get("cameras", [])),
        }

    return diagnostics
