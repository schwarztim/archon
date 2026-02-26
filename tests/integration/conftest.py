"""Shared fixtures for integration tests.

These tests run against a LIVE server (AUTH_DEV_MODE=true, no real auth needed).
Set TEST_BASE_URL env var to override the default base URL.
"""

import os

import httpx
import pytest

BASE_URL = os.getenv("TEST_BASE_URL", "http://localhost:8000")


@pytest.fixture(scope="session")
def client():
    """HTTP client for integration tests."""
    with httpx.Client(base_url=BASE_URL, timeout=30.0) as c:
        yield c


@pytest.fixture(scope="session")
def api_prefix():
    return "/api/v1"
