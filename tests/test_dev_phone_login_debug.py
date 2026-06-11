# ruff: noqa: D102,EM102,PT009,TRY003
"""Tests for the phone login debug helper script."""

from __future__ import annotations

import importlib.util
import sys
import unittest
from pathlib import Path

SCRIPT_PATH = Path("dev/phone_login_debug.py")
spec = importlib.util.spec_from_file_location(
    "phone_login_debug_for_tests",
    SCRIPT_PATH,
)
if spec is None or spec.loader is None:
    raise RuntimeError(f"Cannot load {SCRIPT_PATH}")
phone_login_debug = importlib.util.module_from_spec(spec)
sys.modules[spec.name] = phone_login_debug
spec.loader.exec_module(phone_login_debug)


class PhoneLoginDebugTests(unittest.TestCase):
    """Pure helper behavior for the debug script."""

    def test_normalize_phone_accepts_common_russian_formats(self) -> None:
        self.assertEqual(
            phone_login_debug.normalize_phone("8 (999) 111-22-33"),
            "+79991112233",
        )
        self.assertEqual(
            phone_login_debug.normalize_phone("79991112233"),
            "+79991112233",
        )
        self.assertEqual(
            phone_login_debug.normalize_phone("+79991112233"),
            "+79991112233",
        )

    def test_find_account_by_id_matches_account_id(self) -> None:
        accounts = [
            {"accountId": "first", "address": "First"},
            {"accountId": "second", "address": "Second"},
        ]

        self.assertEqual(
            phone_login_debug.find_account_by_id(accounts, "second"),
            {"accountId": "second", "address": "Second"},
        )

    def test_confirmation_payload_matches_domru_contract(self) -> None:
        account = {
            "accountId": "account-1",
            "profileId": "profile-1",
            "operatorId": 123,
            "subscriberId": 456,
        }

        self.assertEqual(
            phone_login_debug.build_confirmation_payload(
                "+79991112233",
                "1122",
                account,
            ),
            {
                "operatorId": 123,
                "login": "+79991112233",
                "accountId": "account-1",
                "profileId": "profile-1",
                "confirm1": "1122",
                "confirm2": "1122",
                "subscriberId": "456",
            },
        )

    def test_redact_tokens_recurses_through_response(self) -> None:
        response = {
            "accessToken": "access-secret",
            "refreshToken": "refresh-secret",
            "nested": [{"tokenType": "Bearer", "value": "visible"}],
        }

        redacted = phone_login_debug.redact_secrets(response)

        self.assertEqual(redacted["accessToken"], "access...<redacted>")
        self.assertEqual(redacted["refreshToken"], "refres...<redacted>")
        self.assertEqual(redacted["nested"][0]["tokenType"], "Bearer")
        self.assertEqual(redacted["nested"][0]["value"], "visible")

    def test_can_retry_sms_code_only_for_interactive_failures(self) -> None:
        self.assertTrue(phone_login_debug.can_retry_sms_code(500, None))
        self.assertTrue(phone_login_debug.can_retry_sms_code(403, None))
        self.assertFalse(phone_login_debug.can_retry_sms_code(200, None))
        self.assertFalse(phone_login_debug.can_retry_sms_code(500, "0000"))


if __name__ == "__main__":
    unittest.main()
