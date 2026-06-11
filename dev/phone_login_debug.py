#!/usr/bin/env python3
# ruff: noqa: T201
"""Debug Dom.ru phone + SMS login outside Home Assistant."""

from __future__ import annotations

import argparse
import asyncio
import json
from copy import deepcopy
from pathlib import Path
from typing import Any
from urllib.parse import quote, urljoin

BASE_URL = "https://myhome.proptech.ru/"
USER_AGENT = (
    "Google sdkgphone64x8664 | Android 14 | erth | 8.9.2 (8090200) |  | "
    "null | 10c99d90-9899-4a25-926f-067b34bc4a7f | null"
)
RUSSIAN_PHONE_DIGITS = 11
SECRET_KEYS = {
    "accessToken",
    "refreshToken",
    "access_token",
    "refresh_token",
    "authorization",
}


def normalize_phone(phone: str) -> str:
    """Normalize common Russian phone formats to +7XXXXXXXXXX."""
    value = (
        phone.strip()
        .replace(" ", "")
        .replace("-", "")
        .replace("(", "")
        .replace(")", "")
    )
    if value.startswith("8") and len(value) == RUSSIAN_PHONE_DIGITS:
        return f"+7{value[1:]}"
    if value.startswith("7") and len(value) == RUSSIAN_PHONE_DIGITS:
        return f"+{value}"
    return value


def redact_value(value: str | None, *, visible_prefix: int = 6) -> str:
    """Return a safe display value for tokens."""
    if not value:
        return "<missing>"
    if len(value) <= visible_prefix:
        return "<redacted>"
    return f"{value[:visible_prefix]}...<redacted>"


def redact_secrets(value: Any) -> Any:
    """Recursively redact known token fields from JSON-like values."""
    if isinstance(value, dict):
        redacted = {}
        for key, item in value.items():
            redacted[key] = (
                redact_value(str(item)) if key in SECRET_KEYS else redact_secrets(item)
            )
        return redacted
    if isinstance(value, list):
        return [redact_secrets(item) for item in value]
    return value


def find_account_by_id(
    accounts: list[dict[str, Any]],
    account_id: str,
) -> dict[str, Any] | None:
    """Find a phone-login account by accountId."""
    return next(
        (
            account
            for account in accounts
            if str(account.get("accountId")) == account_id
        ),
        None,
    )


def build_confirmation_payload(
    phone: str,
    code: str,
    account: dict[str, Any],
) -> dict[str, Any]:
    """Build the Dom.ru SMS confirmation request body."""
    return {
        "operatorId": account.get("operatorId"),
        "login": phone,
        "accountId": account.get("accountId"),
        "profileId": account.get("profileId"),
        "confirm1": code,
        "confirm2": code,
        "subscriberId": str(account.get("subscriberId")),
    }


def can_retry_sms_code(status: int, initial_sms_code: str | None) -> bool:
    """Return whether the debug flow can prompt for another SMS code."""
    return status >= 400 and initial_sms_code is None


def _headers() -> dict[str, str]:
    """Return Dom.ru mobile-like headers."""
    return {
        "User-Agent": USER_AGENT,
        "Content-Type": "application/json; charset=UTF-8",
        "Connection": "Keep-Alive",
    }


def _dump_json(title: str, payload: Any, *, show_secrets: bool) -> None:
    """Print a labeled JSON payload."""
    safe_payload = payload if show_secrets else redact_secrets(deepcopy(payload))
    print(f"\n{title}")
    print(json.dumps(safe_payload, indent=2, ensure_ascii=False))


async def _request_json(
    session: Any,
    *,
    method: str,
    url: str,
    json_data: dict[str, Any] | None = None,
) -> tuple[int, dict[str, str], Any]:
    """Send an HTTP request and return status, headers, and parsed response."""
    async with session.request(
        method=method,
        url=url,
        json=json_data,
        headers=_headers(),
    ) as response:
        text = await response.text()
        try:
            payload = json.loads(text) if text else None
        except json.JSONDecodeError:
            payload = text
        return response.status, dict(response.headers), payload


def _parse_accounts(payload: Any) -> list[dict[str, Any]]:
    """Extract account list from Dom.ru account lookup response."""
    if isinstance(payload, list):
        return [item for item in payload if isinstance(item, dict)]
    if isinstance(payload, dict):
        data = payload.get("data", payload.get("accounts", []))
        if isinstance(data, list):
            return [item for item in data if isinstance(item, dict)]
    return []


def _account_label(account: dict[str, Any]) -> str:
    """Build a short account label."""
    return str(
        account.get("address")
        or account.get("accountId")
        or account.get("subscriberId")
        or "<unknown>"
    )


def _choose_account(
    accounts: list[dict[str, Any]],
    account_id: str | None,
) -> dict[str, Any]:
    """Choose an account from lookup results."""
    if account_id:
        account = find_account_by_id(accounts, account_id)
        if account is None:
            msg = f"Account {account_id!r} was not returned by Dom.ru"
            raise RuntimeError(msg)
        return account

    if len(accounts) == 1:
        return accounts[0]

    print("\nAccounts:")
    for index, account in enumerate(accounts, start=1):
        print(f"  {index}. {_account_label(account)} [{account.get('accountId')}]")

    while True:
        choice = input("Choose account number: ").strip()
        if choice.isdigit() and 1 <= int(choice) <= len(accounts):
            return accounts[int(choice) - 1]
        print("Invalid account number")


def _write_output(path: Path, payload: dict[str, Any], *, show_secrets: bool) -> None:
    """Write the collected flow output to disk."""
    safe_payload = payload if show_secrets else redact_secrets(deepcopy(payload))
    path.write_text(
        json.dumps(safe_payload, indent=2, ensure_ascii=False), encoding="utf-8"
    )
    print(f"\nSaved collected output to {path}")


async def run_phone_login_debug(args: argparse.Namespace) -> int:
    """Run the interactive phone login debug flow."""
    import aiohttp  # noqa: PLC0415

    phone = normalize_phone(args.phone or input("Phone (+7XXXXXXXXXX): "))
    escaped_phone = quote(phone, safe="")
    base_url = args.base_url.rstrip("/") + "/"
    collected: dict[str, Any] = {"phone": phone, "steps": []}

    async with aiohttp.ClientSession(trust_env=True) as session:
        accounts_url = urljoin(base_url, f"auth/v2/login/{escaped_phone}")
        print(f"\n[1] GET {accounts_url}")
        status, headers, payload = await _request_json(
            session,
            method="GET",
            url=accounts_url,
        )
        collected["steps"].append(
            {
                "name": "accounts",
                "status": status,
                "headers": headers,
                "response": payload,
            }
        )
        print(f"Status: {status}")
        _dump_json("Accounts response:", payload, show_secrets=args.show_secrets)
        if status >= 400:
            msg = f"Account lookup failed with HTTP {status}"
            raise RuntimeError(msg)

        accounts = _parse_accounts(payload)
        if not accounts:
            msg = "Account lookup returned no accounts"
            raise RuntimeError(msg)

        account = _choose_account(accounts, args.account_id)
        _dump_json("Selected account:", account, show_secrets=args.show_secrets)

        confirmation_url = urljoin(base_url, f"auth/v2/confirmation/{escaped_phone}")
        print(f"\n[2] POST {confirmation_url}")
        status, headers, payload = await _request_json(
            session,
            method="POST",
            url=confirmation_url,
            json_data=account,
        )
        collected["steps"].append(
            {
                "name": "request_sms",
                "status": status,
                "headers": headers,
                "request": account,
                "response": payload,
            }
        )
        print(f"Status: {status}")
        _dump_json("SMS request response:", payload, show_secrets=args.show_secrets)
        if status >= 400:
            msg = f"SMS request failed with HTTP {status}"
            raise RuntimeError(msg)

        confirm_url = urljoin(base_url, f"auth/v3/auth/{escaped_phone}/confirmation")
        attempt = 1
        while True:
            sms_code = args.sms_code or input("\nSMS code: ").strip()
            confirm_body = build_confirmation_payload(phone, sms_code, account)
            print(f"\n[3] POST {confirm_url}")
            status, headers, payload = await _request_json(
                session,
                method="POST",
                url=confirm_url,
                json_data=confirm_body,
            )
            collected["steps"].append(
                {
                    "name": "confirm_sms",
                    "attempt": attempt,
                    "status": status,
                    "headers": headers,
                    "request": confirm_body,
                    "response": payload,
                }
            )
            print(f"Status: {status}")
            _dump_json(
                "SMS confirmation response:", payload, show_secrets=args.show_secrets
            )
            if status < 400:
                break
            if not can_retry_sms_code(status, args.sms_code):
                msg = f"SMS confirmation failed with HTTP {status}"
                raise RuntimeError(msg)

            print("\nSMS confirmation failed. Enter another code or press Ctrl+C.")
            attempt += 1

    if args.output:
        _write_output(Path(args.output), collected, show_secrets=args.show_secrets)

    print("\nPhone login debug flow completed.")
    if not args.show_secrets:
        print("Token fields were redacted. Re-run with --show-secrets to inspect them.")
    return 0


def build_parser() -> argparse.ArgumentParser:
    """Build CLI argument parser."""
    parser = argparse.ArgumentParser(
        description="Debug Dom.ru phone + SMS login and print raw responses."
    )
    parser.add_argument("--phone", help="Phone number. Example: +79991112233")
    parser.add_argument(
        "--account-id",
        help="Account ID to use when Dom.ru returns multiple accounts.",
    )
    parser.add_argument(
        "--sms-code", help="SMS code. If omitted, prompts interactively."
    )
    parser.add_argument(
        "--base-url",
        default=BASE_URL,
        help=f"Dom.ru API base URL. Defaults to {BASE_URL}",
    )
    parser.add_argument(
        "--output",
        help="Optional JSON file path for collected responses.",
    )
    parser.add_argument(
        "--show-secrets",
        action="store_true",
        help="Print and save token values instead of redacting them.",
    )
    return parser


def main() -> int:
    """CLI entrypoint."""
    parser = build_parser()
    args = parser.parse_args()
    return asyncio.run(run_phone_login_debug(args))


if __name__ == "__main__":
    raise SystemExit(main())
