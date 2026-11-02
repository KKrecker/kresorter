"""The window's tests reach no live system (decision 0014, item 39)."""

import os
import socket
from pathlib import Path

import pytest

from safeclean.environment import Environment
from safeclean.llm.client import status
from support.live import HOME_VARIABLES, LiveSystemError


def test_the_contexts_of_the_running_system_are_refused() -> None:
    # [0014.39] A window made without an environment for tmp_path cannot read the system.
    with pytest.raises(LiveSystemError):
        Environment().scan_context()
    with pytest.raises(LiveSystemError):
        Environment().autostart_context()


def test_home_and_the_data_and_settings_folders_are_temporary(
    tmp_path_factory: pytest.TempPathFactory,
) -> None:
    # [0014.39]
    home = Path.home()
    assert home.is_relative_to(tmp_path_factory.getbasetemp())
    assert all(Path(os.environ[name]).is_relative_to(home) for name in HOME_VARIABLES)


def test_the_local_ai_of_the_running_system_is_not_asked() -> None:
    # [0014.39] Its address is refused as a setting, before any connection.
    found = status(Environment().llm_env)
    assert found.address is None
    assert found.failure is not None


def test_the_network_guard_holds_for_the_window_s_tests() -> None:
    # [0014.39] 0013 item 29.
    with socket.socket() as sock, pytest.raises(AssertionError, match="beyond loopback"):
        sock.connect(("192.0.2.1", 9))
