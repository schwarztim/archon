"""Tests for the plugin loader."""

from __future__ import annotations

import pytest

from app.plugins.loader import PluginLoader


def test_load_all_returns_enabled_plugins(test_plugins_dir: str) -> None:
    loader = PluginLoader()
    plugins = loader.load_all(test_plugins_dir)
    names = {p.name for p in plugins}
    assert "test-finance" in names
    assert "test-public" in names


def test_disabled_plugin_not_loaded(tmp_path: pytest.TempPath) -> None:
    (tmp_path / "disabled.yaml").write_text(
        "name: disabled-plugin\ndisplay_name: Disabled\nenabled: false\n",
        encoding="utf-8",
    )
    loader = PluginLoader()
    plugins = loader.load_all(str(tmp_path))
    assert not plugins


def test_invalid_yaml_skipped(tmp_path: pytest.TempPath) -> None:
    (tmp_path / "bad.yaml").write_text(":::invalid yaml:::\n", encoding="utf-8")
    loader = PluginLoader()
    plugins = loader.load_all(str(tmp_path))
    assert not plugins


def test_missing_required_field_skipped(tmp_path: pytest.TempPath) -> None:
    # 'name' is required
    (tmp_path / "noname.yaml").write_text("display_name: NoName\n", encoding="utf-8")
    loader = PluginLoader()
    plugins = loader.load_all(str(tmp_path))
    assert not plugins


def test_get_plugin_by_name(test_plugins_dir: str) -> None:
    loader = PluginLoader()
    loader.load_all(test_plugins_dir)
    plugin = loader.get_plugin("test-finance")
    assert plugin is not None
    assert plugin.name == "test-finance"


def test_get_tool_by_id(test_plugins_dir: str) -> None:
    loader = PluginLoader()
    loader.load_all(test_plugins_dir)
    tool = loader.get_tool("get_revenue")
    assert tool is not None
    assert tool.id == "get_revenue"


def test_get_unknown_tool_returns_none(test_plugins_dir: str) -> None:
    loader = PluginLoader()
    loader.load_all(test_plugins_dir)
    assert loader.get_tool("nonexistent_tool") is None


def test_nonexistent_dir_returns_empty() -> None:
    loader = PluginLoader()
    plugins = loader.load_all("/nonexistent/path/that/does/not/exist")
    assert plugins == []


def test_len(test_plugins_dir: str) -> None:
    loader = PluginLoader()
    loader.load_all(test_plugins_dir)
    assert len(loader) == 2
