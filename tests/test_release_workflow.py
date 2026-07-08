# ruff: noqa: D102
"""Tests for GitHub release workflow version selection."""

import unittest
from pathlib import Path


class ReleaseWorkflowTests(unittest.TestCase):
    """Release workflow behavior checks."""

    def test_stable_release_ignores_beta_tags(self) -> None:
        workflow = Path(".github/workflows/release.yml").read_text()

        assert 'git", "tag"' in workflow
        assert "stable_tags" in workflow
        assert "--abbrev=0" not in workflow


if __name__ == "__main__":
    unittest.main()
