"""Test fixtures: fake the Omega config API and make the plugin importable.

The plugin imports the stock Omega configuration API
(``from config import config_get_by_key``). That module only exists inside
the Omega image; tests substitute a minimal fake with the same lookup
semantics as ``src/config.py``: explicit values first, then the default.
"""

from __future__ import annotations

import sys
import types
from pathlib import Path

import pytest

PLUGIN_DIR = Path(__file__).resolve().parent.parent
if str(PLUGIN_DIR) not in sys.path:
    sys.path.insert(0, str(PLUGIN_DIR))

if "config" not in sys.modules:
    _fake_config = types.ModuleType("config")
    _fake_config._values = {}

    def config_get_by_key(key, default=None):
        """Mirror src/config.py resolution: value, then default."""
        return _fake_config._values.get(key, default)

    _fake_config.config_get_by_key = config_get_by_key
    sys.modules["config"] = _fake_config


@pytest.fixture()
def cfg(monkeypatch):
    """Fresh config values dict for the fake config module."""
    values: dict = {}
    monkeypatch.setattr(sys.modules["config"], "_values", values)
    return values
