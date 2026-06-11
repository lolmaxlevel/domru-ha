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


if __name__ == "__main__":
    unittest.main()
