"""Test-wide guard: no test may open a network connection (no real model calls, no cost)."""

import socket

import pytest


class NetworkDisabled(OSError):
    pass


def _blocked(*args, **kwargs):
    raise NetworkDisabled("network disabled in tests")


@pytest.fixture(autouse=True)
def _signed_staff_identity(monkeypatch):
    """Apps built in tests verify the tokens from tests.auth_headers; plain X-Role headers are refused."""
    from tests.auth_headers import TEST_AUTH_SECRET
    monkeypatch.setenv("GOVFLOW_AUTH_SECRET", TEST_AUTH_SECRET)
    monkeypatch.delenv("GOVFLOW_DEMO_INSECURE", raising=False)


@pytest.fixture(autouse=True)
def _no_network(monkeypatch):
    monkeypatch.setattr(socket.socket, "connect", _blocked)
    monkeypatch.setattr(socket, "create_connection", _blocked)
