# ruff: noqa: D103,D213,INP001,T201
"""Probe Dom.ru endpoints that need live response samples before HA wiring.

Usage:
    python dev/probe_upstream_endpoints.py --username LOGIN --password PASSWORD
    python dev/probe_upstream_endpoints.py --refresh-token TOKEN --operator-id 2

Optional:
    --place-id PLACE --camera-id CAMERA --access-control-id DEVICE --entrance-id ID
    --archive-ts 1720000000 --archive-tz 10800
"""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import sys
from datetime import UTC, datetime, timedelta
from importlib import util
from pathlib import Path
from typing import Any
from urllib.parse import quote, urljoin

import aiohttp

ROOT = Path(__file__).resolve().parents[1]
API_MODULE_PATH = ROOT / "custom_components" / "domru" / "api.py"


def _load_domru_api_module() -> Any:
    spec = util.spec_from_file_location("domru_api_for_probe", API_MODULE_PATH)
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


def _json_default(value: Any) -> str:
    return str(value)


def _print_json(title: str, value: Any) -> None:
    print(f"\n=== {title} ===")
    print(json.dumps(value, ensure_ascii=False, indent=2, default=_json_default))


def _response_shape(value: Any) -> Any:
    if isinstance(value, dict):
        return {key: _response_shape(item) for key, item in value.items()}
    if isinstance(value, list):
        if not value:
            return []
        return [_response_shape(value[0]), f"... {len(value)} item(s) total"]
    return type(value).__name__


def _first_id(items: list[dict[str, Any]], *keys: str) -> Any:
    for item in items:
        for key in keys:
            value = item.get(key)
            if value is not None:
                return value
    return None


def camera_id_from_sources(
    cameras: list[dict[str, Any]],
    access_controls: list[dict[str, Any]],
) -> Any:
    return _first_id(
        cameras,
        "externalCameraId",
        "external_camera_id",
        "ID",
        "id",
    ) or _first_id(
        access_controls,
        "externalCameraId",
        "external_camera_id",
    )


async def _probe_binary(
    client: DomruApiClient,
    title: str,
    path: str,
) -> None:
    url = urljoin(client.BASE_URL, path)
    async with client._session.request(  # noqa: SLF001
        method="GET",
        url=url,
        headers=client._get_headers(),  # noqa: SLF001
    ) as response:
        body = await response.read()
        _print_json(
            title,
            {
                "url": url,
                "status": response.status,
                "content_type": response.headers.get("Content-Type"),
                "bytes": len(body),
                "first_bytes_hex": body[:16].hex(),
            },
        )


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

        places = await client.get_subscriber_places()
        _print_json("rest/v3/subscriber-places shape", _response_shape(places))
        _print_json("rest/v3/subscriber-places sample", places[:1])

        place_id = args.place_id
        if place_id is None and places:
            place = places[0].get("place", places[0])
            if isinstance(place, dict):
                place_id = place.get("id")

        if place_id is None:
            print("\nNo place ID found; skipping place-scoped probes.")
            return

        access_controls = await client.get_access_controls(place_id)
        _print_json("accesscontrols shape", _response_shape(access_controls))
        _print_json("accesscontrols sample", access_controls[:1])

        cameras = await client.get_cameras(place_id=place_id)
        _print_json("place cameras shape", _response_shape(cameras))
        _print_json("place cameras sample", cameras[:1])

        camera_id = args.camera_id or camera_id_from_sources(cameras, access_controls)
        access_control_id = args.access_control_id or _first_id(access_controls, "id")

        if access_control_id is not None:
            await _probe_binary(
                client,
                "access-control videosnapshots",
                f"rest/v1/places/{place_id}/accesscontrols/"
                f"{access_control_id}/videosnapshots",
            )

        if access_control_id is not None and args.entrance_id is not None:
            try:
                result = await client.async_open_entrance(
                    place_id=place_id,
                    access_control_id=access_control_id,
                    entrance_id=args.entrance_id,
                )
            except DomruApiClientError as exc:
                result = {"error": str(exc)}
            _print_json("open entrance result", result)

        if camera_id is None:
            print("\nNo camera ID found; skipping camera video/event probes.")
            return

        refresh = await client._api_wrapper(  # noqa: SLF001
            method="PUT",
            url=urljoin(
                client.BASE_URL,
                "api/mh-camera-personal/mobile/v1/video/"
                f"refresh-user-session?externalCameraId={camera_id}",
            ),
        )
        _print_json("refresh-user-session shape", _response_shape(refresh))
        _print_json("refresh-user-session sample", refresh)

        hls = await client._api_wrapper(  # noqa: SLF001
            method="GET",
            url=urljoin(
                client.BASE_URL,
                f"rest/v1/forpost/cameras/{camera_id}/video?LightStream=0&Format=HLS",
            ),
        )
        _print_json("HLS video shape", _response_shape(hls))
        _print_json("HLS video sample", hls)

        if args.archive_ts is not None:
            archive = await client._api_wrapper(  # noqa: SLF001
                method="GET",
                url=urljoin(
                    client.BASE_URL,
                    f"rest/v1/forpost/cameras/{camera_id}/video?"
                    f"TS={args.archive_ts}&TZ={args.archive_tz}&"
                    "LightStream=0&Format=HLS",
                ),
            )
            _print_json("archive video shape", _response_shape(archive))
            _print_json("archive video sample", archive)

        now = datetime.now(UTC)
        lower = quote((now - timedelta(days=1)).strftime("%Y-%m-%dT%H:%M:%SZ"))
        upper = quote(now.strftime("%Y-%m-%dT%H:%M:%SZ"))
        events = await client._api_wrapper(  # noqa: SLF001
            method="GET",
            url=urljoin(
                client.BASE_URL,
                f"rest/v2/forpost/cameras/{camera_id}/events?"
                f"LowerDate={lower}&UpperDate={upper}&Count=200&orderByTime=DESC",
            ),
        )
        _print_json("camera events shape", _response_shape(events))
        _print_json("camera events sample", events)


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
    parser.add_argument("--entrance-id", default=os.getenv("DOMRU_ENTRANCE_ID"))
    parser.add_argument("--archive-ts", type=int, default=None)
    parser.add_argument("--archive-tz", type=int, default=10800)
    return parser.parse_args()


if __name__ == "__main__":
    asyncio.run(run(parse_args()))
