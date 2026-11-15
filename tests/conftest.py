"""Test-wide guard: no test may open a network connection (no real model calls, no cost)."""

import socket

import pytest


class NetworkDisabled(OSError):
    pass


def _blocked(*args, **kwargs):
    raise NetworkDisabled("network disabled in tests")


@pytest.fixture(autouse=True)
def _no_network(monkeypatch):
    monkeypatch.setattr(socket.socket, "connect", _blocked)
    monkeypatch.setattr(socket, "create_connection", _blocked)
