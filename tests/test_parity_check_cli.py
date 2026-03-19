from __future__ import annotations

from cli import main


def test_parity_check_command_returns_success() -> None:
    rc = main(["parity-check"])
    assert rc == 0

