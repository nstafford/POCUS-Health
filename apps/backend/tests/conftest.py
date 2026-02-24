"""Pytest configuration and shared fixtures."""

import pytest


@pytest.fixture(autouse=True)
def reset_sessions():
    """Reset sessions before each test."""
    from app.main import sessions
    sessions.clear()
    yield
    sessions.clear()
