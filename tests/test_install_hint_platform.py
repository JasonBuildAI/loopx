"""Install/repair guidance LoopX prints must run on the host that prints it.

The bootstrap/connect hint is the first repair instruction a new operator sees.
Native Windows has no ``python3`` launcher and no Bash, while ``loopx doctor``
already names the interpreter and snapshot installer this host owns. These
tests pin that platform rule, not one rendered string.
"""

from __future__ import annotations

import os
import shlex
import sys
from pathlib import Path

import pytest

from loopx import install_contract
from loopx.bootstrap import bootstrap_project

POSIX_ONLY_TOKENS = ("python3 ", "| bash", "export PATH=")


def bootstrap_hint(tmp_path: Path) -> tuple[str, str]:
    registry = tmp_path / ".loopx" / "registry.json"
    registry.parent.mkdir(parents=True, exist_ok=True)
    payload = bootstrap_project(
        project=tmp_path,
        registry_path=registry,
        runtime_root=tmp_path / "runtime",
        goal_id="install-hint-goal",
        objective="Print install guidance.",
        domain="test",
        role="controller",
        parent_goal_id=None,
        state_file=None,
        goal_doc=None,
        adapter_kind="generic_project_goal_v0",
        adapter_status="connected",
        next_probe=None,
        spawn_allowed=False,
        max_children=0,
        allowed_domains=[],
        write_scope=[],
        force=False,
        dry_run=True,
        sync_global=False,
    )
    return str(payload["install_repair_command"]), str(
        payload["archive_fallback_install_command"]
    )


@pytest.mark.parametrize("os_name", ["posix", "nt"])
def test_install_hint_commands_follow_the_host_platform(
    monkeypatch: pytest.MonkeyPatch, os_name: str
) -> None:
    monkeypatch.setattr(os, "name", os_name)
    repair = install_contract.install_repair_command()
    fallback = install_contract.archive_fallback_install_command()

    if os_name == "nt":
        for command in (repair, fallback):
            for token in POSIX_ONLY_TOKENS:
                assert token not in command, command
        assert repair.startswith(f"{shlex.quote(sys.executable)} -m pip install")
        assert "loopx workflow-skills --install" in repair
        assert "loopx doctor" in repair
        assert "install-windows.ps1" in fallback
        assert "curl" not in fallback
    else:
        assert repair == install_contract.DEFAULT_INSTALL_REPAIR_COMMAND
        assert fallback == install_contract.ARCHIVE_FALLBACK_INSTALL_COMMAND


def test_bootstrap_payload_prints_commands_this_host_can_run(tmp_path: Path) -> None:
    repair, fallback = bootstrap_hint(tmp_path)
    assert "loopx doctor" in repair
    assert "loopx doctor" in fallback
    if os.name == "nt":
        for command in (repair, fallback):
            for token in POSIX_ONLY_TOKENS:
                assert token not in command, command
        assert "install-windows.ps1" in fallback
    else:
        assert repair == install_contract.DEFAULT_INSTALL_REPAIR_COMMAND
        assert fallback == install_contract.ARCHIVE_FALLBACK_INSTALL_COMMAND
