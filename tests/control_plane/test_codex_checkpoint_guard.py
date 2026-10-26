"""The interrupted native guard binds the rendered default-off heartbeat call.

A capture is accepted only when the native command matches the held packet. The
CLI keeps an omitted ``--context-delivery`` distinct from an explicit ``off`` so
a machine default can apply, while the heartbeat renderer spells the option only
for an enabled mode. A default-off capture therefore arrives with the option
omitted; that is the off mode, not an unknown mode.
"""
from __future__ import annotations

import shlex

import pytest

from loopx.hosts.codex_checkpoint import _verify_interrupted_guard


GUARD = {
    "cli": "/fixture/loopx",
    "workspace": "/fixture/workspace",
    "registry": "/fixture/registry.json",
    "runtime_root": "/fixture/runtime",
    "goal_id": "research",
    "agent_id": "worker",
    "turn_instance_id": "turn-1",
    "capture_root": "/fixture/decisions",
    "socket_path": "/fixture/socket",
    "decision_sha256": "a" * 64,
}


def _turns(*extra: str) -> list[dict]:
    argv = [
        GUARD["cli"], "--registry", GUARD["registry"], "--runtime-root", GUARD["runtime_root"],
        "--format", "json", "quota", "should-run", "--goal-id", GUARD["goal_id"],
        "--agent-id", GUARD["agent_id"], "--turn-instance-id", GUARD["turn_instance_id"],
        "--turn-envelope", "--decision-output-root", GUARD["capture_root"],
        "--decision-handoff-socket", GUARD["socket_path"], *extra,
    ]
    command = shlex.join(["/bin/bash", "-lc", shlex.join(argv)])
    item = {"type": "commandExecution", "id": "guard-call", "command": command,
            "cwd": GUARD["workspace"], "status": "failed", "exitCode": 137,
            "aggregatedOutput": None}
    return [{"id": "retained-compaction", "status": "completed",
             "items": [{"type": "contextCompaction"}]},
            {"id": "pending", "status": "interrupted", "items": [item]}]


@pytest.mark.parametrize("extra", [(), ("--context-delivery", "off")])
def test_default_off_capture_binds_an_omitted_context_delivery(extra):
    _verify_interrupted_guard(_turns(*extra), GUARD)


def test_explicit_on_capture_does_not_bind_the_default_off_guard():
    with pytest.raises(ValueError, match="guard differs"):
        _verify_interrupted_guard(_turns("--context-delivery", "on"), GUARD)
