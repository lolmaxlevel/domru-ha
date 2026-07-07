# ruff: noqa: D103,D213,INP001,T201
"""Discover known and likely Dom.ru API endpoints for the current account.

Usage:
    python dev/discover_endpoints.py --username LOGIN --password PASSWORD
    python dev/discover_endpoints.py --refresh-token TOKEN --operator-id 2

By default the script skips endpoints that can open doors or create SIP devices.
Pass --include-actions only when you intentionally want to probe those.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import sys
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from importlib import util
from pathlib import Path
from typing import Any
from urllib.parse import quote, urljoin

import aiohttp

ROOT = Path(__file__).resolve().parents[1]
API_MODULE_PATH = ROOT / "custom_components" / "domru" / "api.py"


def _load_domru_api_module() -> Any:
    spec = util.spec_from_file_location("domru_api_for_discovery", API_MODULE_PATH)
    if spec is None or spec.loader is None:
        msg = f"Cannot load {API_MODULE_PATH}"
        raise RuntimeError(msg)
    module = util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


_api_module = _load_domru_api_module()
DomruApiClient = _api_module.DomruApiClient
DomruApiClientError = _api_module.DomruApiClientError

DOC_PATHS = (
    "swagger",
    "swagger/",
    "swagger.json",
    "swagger-ui",
    "swagger-ui/",
    "openapi.json",
    "api-docs",
    "api-docs/",
    "v3/api-docs",
    "v2/api-docs",
    "rest/v3/api-docs",
    "rest/v2/api-docs",
    "rest/v1/api-docs",
)
HTTP_OK = 200
HTTP_BAD_REQUEST = 400


@dataclass(frozen=True)
class EndpointProbe:
    """Endpoint probe definition."""

    version: str
    method: str
    path: str
    description: str
    body: dict[str, Any] | None = None
    side_effect: bool = False
    binary: bool = False


def _json_default(value: Any) -> str:
    return str(value)


def _print_json(title: str, value: Any) -> None:
    print(f"\n=== {title} ===")
    print(json.dumps(value, ensure_ascii=False, indent=2, default=_json_default))


def response_shape(value: Any) -> Any:
    """Return a compact type shape for JSON-compatible values."""
    if isinstance(value, dict):
        return {key: response_shape(item) for key, item in value.items()}
    if isinstance(value, list):
        if not value:
            return []
        return [response_shape(value[0]), f"... {len(value)} item(s) total"]
    return type(value).__name__


def _first_id(items: list[dict[str, Any]], *keys: str) -> Any:
    for item in items:
        for key in keys:
            value = item.get(key)
            if value is not None:
                return value
    return None


def _first_nested_id(items: list[dict[str, Any]], collection: str, key: str) -> Any:
    for item in items:
        nested = item.get(collection)
        if not isinstance(nested, list):
            continue
        for nested_item in nested:
            if isinstance(nested_item, dict) and nested_item.get(key) is not None:
                return nested_item[key]
    return None


def endpoint_probes(*, include_actions: bool = False) -> list[EndpointProbe]:
    """Return curated endpoint probes."""
    probes = [
        EndpointProbe("v3", "GET", "rest/v3/subscriber-places", "subscriber places"),
        EndpointProbe("v1", "GET", "rest/v1/subscriberplaces", "old subscriber places"),
        EndpointProbe(
            "v1", "GET", "rest/v1/subscribers/profiles", "subscriber profile"
        ),
        EndpointProbe(
            "v1",
            "GET",
            "rest/v1/subscribers/profiles/finances",
            "subscriber finances",
        ),
        EndpointProbe(
            "v1",
            "GET",
            "rest/v1/places/{place_id}/accesscontrols",
            "place access controls",
        ),
        EndpointProbe(
            "v1",
            "GET",
            "rest/v1/places/{place_id}/cameras",
            "place cameras",
        ),
        EndpointProbe("v1", "GET", "rest/v1/forpost/cameras", "forpost cameras"),
        EndpointProbe(
            "v1",
            "GET",
            "rest/v1/forpost/cameras/{camera_id}/snapshots",
            "forpost camera snapshot",
            binary=True,
        ),
        EndpointProbe(
            "v1",
            "GET",
            "rest/v1/places/{place_id}/accesscontrols/{access_control_id}/videosnapshots",
            "access-control snapshot",
            binary=True,
        ),
        EndpointProbe(
            "v1",
            "GET",
            "rest/v1/forpost/cameras/{camera_id}/video?LightStream=0",
            "camera video default format",
        ),
        EndpointProbe(
            "v1",
            "GET",
            "rest/v1/forpost/cameras/{camera_id}/video?LightStream=0&Format=HLS",
            "camera video HLS",
        ),
        EndpointProbe(
            "v2",
            "GET",
            "rest/v2/forpost/cameras/{camera_id}/events?LowerDate={lower_date}&UpperDate={upper_date}&Count=200&orderByTime=DESC",
            "per-camera events",
        ),
        EndpointProbe(
            "v1",
            "GET",
            "rest/v1/places/{place_id}/events?allowExtentedActions=true",
            "place events",
        ),
        EndpointProbe(
            "v1",
            "GET",
            "rest/v1/temporal-codes?accessControlIds={access_control_id}",
            "temporal access codes",
        ),
        EndpointProbe(
            "v1",
            "POST",
            "rest/v1/events/search?page=0&sort=occurredAt,DESC",
            "events search",
            body={"placeIds": ["{place_id}"]},
        ),
        EndpointProbe(
            "mh-camera v1",
            "PUT",
            "api/mh-camera-personal/mobile/v1/video/refresh-user-session?externalCameraId={camera_id}",
            "refresh camera session",
        ),
        EndpointProbe(
            "v1",
            "POST",
            "rest/v1/places/{place_id}/accesscontrols/{access_control_id}/sipdevices",
            "create SIP device",
            body={"installationId": "domru-discovery-probe"},
            side_effect=True,
        ),
        EndpointProbe(
            "v1",
            "POST",
            "rest/v1/places/{place_id}/accesscontrols/{access_control_id}/actions",
            "open access control",
            body={"name": "accessControlOpen"},
            side_effect=True,
        ),
        EndpointProbe(
            "v1",
            "POST",
            "rest/v1/places/{place_id}/accesscontrols/{access_control_id}/entrances/{entrance_id}/actions",
            "open access-control entrance",
            body={"name": "accessControlOpen"},
            side_effect=True,
        ),
        EndpointProbe(
            "v1",
            "POST",
            "rest/v1/forpost/cameras/{camera_id}/devices/{external_device_id}/open",
            "open FORPOST device",
            side_effect=True,
        ),
    ]
    if include_actions:
        return probes
    return [probe for probe in probes if not probe.side_effect]


def _stringify_values(value: Any, variables: dict[str, Any]) -> Any:
    if isinstance(value, dict):
        return {key: _stringify_values(item, variables) for key, item in value.items()}
    if isinstance(value, list):
        return [_stringify_values(item, variables) for item in value]
    if isinstance(value, str):
        try:
            return value.format(**variables)
        except KeyError:
            return value
    return value


def render_probe(
    probe: EndpointProbe,
    variables: dict[str, Any],
) -> tuple[str, dict[str, Any] | None] | None:
    """Render a probe path and body, or None when required variables are absent."""
    try:
        path = probe.path.format(**variables)
    except KeyError:
        return None
    body = _stringify_values(probe.body, variables) if probe.body is not None else None
    return path, body


def _version_key(version: str) -> str:
    if version.startswith("v"):
        return version
    return "other"


async def _fetch_binary(
    client: DomruApiClient,
    method: str,
    path: str,
    body: dict[str, Any] | None,
) -> dict[str, Any]:
    url = urljoin(client.BASE_URL, path)
    async with client._session.request(  # noqa: SLF001
        method=method,
        url=url,
        headers=client._get_headers(),  # noqa: SLF001
        json=body,
    ) as response:
        payload = await response.read()
        return {
            "status": response.status,
            "content_type": response.headers.get("Content-Type"),
            "bytes": len(payload),
            "first_bytes_hex": payload[:16].hex(),
        }


async def _probe_endpoint(
    client: DomruApiClient,
    probe: EndpointProbe,
    path: str,
    body: dict[str, Any] | None,
) -> dict[str, Any]:
    if probe.binary:
        result = await _fetch_binary(client, probe.method, path, body)
        return {"ok": HTTP_OK <= result["status"] < HTTP_BAD_REQUEST, **result}

    try:
        result = await client._api_wrapper(  # noqa: SLF001
            method=probe.method,
            url=urljoin(client.BASE_URL, path),
            json=body,
        )
    except DomruApiClientError as exc:
        return {"ok": False, "error": str(exc)}

    return {"ok": True, "shape": response_shape(result), "sample": result}


async def _probe_docs(
    session: aiohttp.ClientSession, client: DomruApiClient
) -> list[dict[str, Any]]:
    results = []
    for path in DOC_PATHS:
        url = urljoin(client.BASE_URL, path)
        try:
            async with session.get(url, headers=client._get_headers()) as response:  # noqa: SLF001
                text = await response.text()
                results.append(
                    {
                        "path": path,
                        "status": response.status,
                        "content_type": response.headers.get("Content-Type"),
                        "bytes": len(text.encode()),
                        "looks_useful": response.status < HTTP_BAD_REQUEST
                        and (
                            "openapi" in text[:500].lower()
                            or "swagger" in text[:500].lower()
                        ),
                    }
                )
        except (TimeoutError, aiohttp.ClientError) as exc:
            results.append({"path": path, "status": "error", "error": str(exc)})
    return results


async def _discover_context(
    client: DomruApiClient,
    args: argparse.Namespace,
) -> dict[str, Any]:
    places = await client.get_subscriber_places()
    place_id = args.place_id
    if place_id is None and places:
        place = places[0].get("place", places[0])
        if isinstance(place, dict):
            place_id = place.get("id")

    access_controls = []
    if place_id is not None:
        access_controls = await client.get_access_controls(place_id)

    cameras = (
        await client.get_cameras(place_id=place_id) if place_id is not None else []
    )
    camera_id = (
        args.camera_id
        or _first_id(
            cameras,
            "externalCameraId",
            "external_camera_id",
            "ID",
            "id",
        )
        or _first_id(access_controls, "externalCameraId", "external_camera_id")
    )

    now = datetime.now(UTC)
    return {
        "place_id": place_id,
        "access_control_id": args.access_control_id or _first_id(access_controls, "id"),
        "camera_id": camera_id,
        "external_device_id": args.external_device_id
        or _first_id(access_controls, "externalDeviceId", "external_device_id"),
        "entrance_id": args.entrance_id
        or _first_nested_id(access_controls, "entrances", "id"),
        "lower_date": quote((now - timedelta(days=1)).strftime("%Y-%m-%dT%H:%M:%SZ")),
        "upper_date": quote(now.strftime("%Y-%m-%dT%H:%M:%SZ")),
        "places_shape": response_shape(places),
        "access_controls_shape": response_shape(access_controls),
        "cameras_shape": response_shape(cameras),
    }


async def run(args: argparse.Namespace) -> None:
    async with aiohttp.ClientSession() as session:
        client = DomruApiClient(
            username=args.username,
            password=args.password,
            session=session,
            refresh_token=args.refresh_token,
            operator_id=args.operator_id,
        )
        await client.async_authenticate()

        context = await _discover_context(client, args)
        _print_json("context", context)

        docs = await _probe_docs(session, client)
        _print_json("documentation endpoints", docs)

        results: dict[str, list[dict[str, Any]]] = {
            "v3": [],
            "v2": [],
            "v1": [],
            "other": [],
        }
        for probe in endpoint_probes(include_actions=args.include_actions):
            rendered = render_probe(probe, context)
            if rendered is None:
                results[_version_key(probe.version)].append(
                    {
                        "method": probe.method,
                        "path": probe.path,
                        "description": probe.description,
                        "skipped": "missing template variable",
                    }
                )
                continue

            path, body = rendered
            result = await _probe_endpoint(client, probe, path, body)
            results[_version_key(probe.version)].append(
                {
                    "method": probe.method,
                    "path": path,
                    "description": probe.description,
                    "side_effect": probe.side_effect,
                    **result,
                }
            )

        _print_json("endpoint probes", results)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--username", default=os.getenv("DOMRU_USERNAME"))
    parser.add_argument("--password", default=os.getenv("DOMRU_PASSWORD"))
    parser.add_argument("--refresh-token", default=os.getenv("DOMRU_REFRESH_TOKEN"))
    parser.add_argument("--operator-id", default=os.getenv("DOMRU_OPERATOR_ID"))
    parser.add_argument("--place-id", default=os.getenv("DOMRU_PLACE_ID"))
    parser.add_argument("--camera-id", default=os.getenv("DOMRU_CAMERA_ID"))
    parser.add_argument(
        "--access-control-id",
        default=os.getenv("DOMRU_ACCESS_CONTROL_ID"),
    )
    parser.add_argument(
        "--external-device-id", default=os.getenv("DOMRU_EXTERNAL_DEVICE_ID")
    )
    parser.add_argument("--entrance-id", default=os.getenv("DOMRU_ENTRANCE_ID"))
    parser.add_argument(
        "--include-actions",
        action="store_true",
        help="Probe side-effect endpoints that may open doors or create SIP devices.",
    )
    return parser.parse_args()


if __name__ == "__main__":
    asyncio.run(run(parse_args()))
