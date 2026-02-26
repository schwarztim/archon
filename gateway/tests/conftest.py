"""Shared pytest fixtures for the gateway test suite."""

from __future__ import annotations

import os

import pytest
from fastapi.testclient import TestClient

# Ensure dev mode is enabled for all tests
os.environ["AUTH_DEV_MODE"] = "true"
os.environ["PLUGINS_DIR"] = "tests/fixtures/plugins"


@pytest.fixture(scope="session")
def test_plugins_dir(tmp_path_factory: pytest.TempPathFactory) -> str:
    """Create a temporary plugins directory with test YAML files."""
    plugins_dir = tmp_path_factory.mktemp("plugins")

    # Write a test plugin
    (plugins_dir / "test-finance.yaml").write_text(
        """
name: test-finance
display_name: "Test Finance"
version: "0.1.0"
enabled: true
description: "Test plugin"
type: forward
endpoint: "http://localhost:9999"
required_groups:
  - MCP-Users-Finance
tools:
  - id: get_revenue
    description: "Get revenue"
    can_forward: true
    input_schema:
      type: object
      properties:
        period:
          type: string
""",
        encoding="utf-8",
    )

    # Write a public plugin (no group restriction)
    (plugins_dir / "test-public.yaml").write_text(
        """
name: test-public
display_name: "Test Public"
version: "0.1.0"
enabled: true
description: "Public plugin, no group restriction"
type: builtin
tools:
  - id: public_tool
    description: "A public tool"
    can_forward: false
    input_schema:
      type: object
""",
        encoding="utf-8",
    )

    return str(plugins_dir)


@pytest.fixture()
def client(test_plugins_dir: str) -> TestClient:
    """Return a TestClient with dev auth and test plugins loaded."""
    from app.config import get_settings
    from app.main import create_app
    from app.plugins.loader import plugin_loader

    # Override settings
    settings = get_settings()
    settings.__dict__["plugins_dir"] = test_plugins_dir
    settings.__dict__["auth_dev_mode"] = True

    plugin_loader.load_all(test_plugins_dir)

    app = create_app()
    return TestClient(app, raise_server_exceptions=True)


@pytest.fixture()
def dev_headers() -> dict[str, str]:
    """Authorization headers for the dev bypass user."""
    return {"Authorization": "Bearer dev-token"}
