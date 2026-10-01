"""Shared fixtures."""

import importlib.util

import pytest

# The HA test harness only installs on Linux/macOS; pure-logic tests still run without it.
if importlib.util.find_spec("pytest_homeassistant_custom_component"):

    @pytest.fixture(autouse=True)
    def auto_enable_custom_integrations(enable_custom_integrations):
        """Allow Home Assistant to load custom_components in tests."""
        yield
