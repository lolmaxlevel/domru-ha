# ruff: noqa: D102,PT009
"""Compatibility checks for the Home Assistant config flow."""

import unittest
from pathlib import Path


class ConfigFlowCompatibilityTests(unittest.TestCase):
    """Config flow compatibility with pinned Home Assistant selectors."""

    def test_config_flow_does_not_use_unavailable_select_selector_option(self) -> None:
        source = Path("custom_components/domru/config_flow.py").read_text()

        self.assertNotIn("SelectSelectorOption", source)

    def test_config_flow_can_show_api_error_text(self) -> None:
        source = Path("custom_components/domru/config_flow.py").read_text()
        translations = Path("custom_components/domru/translations/en.json").read_text()

        self.assertIn('"api_error"', translations)
        self.assertIn("description_placeholders", source)
        self.assertIn("error_message", source)

    def test_options_flow_does_not_assign_read_only_config_entry(self) -> None:
        source = Path("custom_components/domru/config_flow.py").read_text()

        self.assertNotIn("self.config_entry =", source)
        self.assertIn("self._config_entry =", source)

    def test_phone_flow_stores_normalized_client_tokens(self) -> None:
        source = Path("custom_components/domru/config_flow.py").read_text()

        self.assertIn("client.refresh_token", source)
        self.assertIn("client.operator_id", source)

    def test_sip_mode_defaults_to_fcm_on_demand(self) -> None:
        config_flow = Path("custom_components/domru/config_flow.py").read_text()
        setup = Path("custom_components/domru/__init__.py").read_text()

        self.assertIn("CONF_SIP_MODE, DEFAULT_SIP_MODE", config_flow)
        self.assertIn("CONF_SIP_MODE, DEFAULT_SIP_MODE", setup)


if __name__ == "__main__":
    unittest.main()
