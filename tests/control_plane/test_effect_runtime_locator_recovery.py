"""A damaged locator must not hide or duplicate a live managed runtime."""
from __future__ import annotations

import json
import subprocess
import sys
import time
from pathlib import Path
from uuid import uuid4

from loopx.control_plane import effect_runtime
from loopx.doctor import render_doctor_markdown


def _runtime_info_path() -> Path:
    fingerprint = effect_runtime._runtime_fingerprint()
    return effect_runtime._runtime_info_path(fingerprint)


def _isolate_runtime(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setattr(effect_runtime, "_runtime_dir", lambda: tmp_path / "runtime")
    monkeypatch.setenv("LOOPX_EFFECT_RUNTIME_IDLE_MS", "60000")


def _shutdown_info(info: dict[str, object]) -> None:
    try:
        effect_runtime._request_with_info(
            info,
            request_id=uuid4().hex,
            method="runtime.shutdown",
            params={},
            timeout=2,
        )
    except (OSError, RuntimeError):
        return
    pid = info.get("pid")
    deadline = time.monotonic() + 5
    while effect_runtime._pid_is_alive(pid) and time.monotonic() < deadline:
        time.sleep(0.05)


def test_corrupt_schema_version_reuses_live_runtime_and_reports_its_liveness(
    tmp_path: Path,
    monkeypatch,
) -> None:
    _isolate_runtime(tmp_path, monkeypatch)
    first = effect_runtime.effect_runtime_result("runtime.ping", {})
    info_path = _runtime_info_path()
    original = json.loads(info_path.read_text(encoding="utf-8"))
    try:
        info_path.write_text(
            json.dumps({**original, "schema_version": "loopx_effect_runtime_info_v1"}),
            encoding="utf-8",
        )

        readiness = effect_runtime.collect_effect_runtime_readiness()
        second = effect_runtime.effect_runtime_result("runtime.ping", {})

        lifecycle = readiness["runtime_lifecycle"]
        assert readiness["ready"] is True
        assert lifecycle["state"] == "running"
        assert lifecycle["locator_state"] == "invalid"
        assert lifecycle["recorded_pid_alive"] is True
        assert lifecycle["diagnostic_code"] == "runtime_locator_schema_mismatch"
        assert second["pid"] == first["pid"]
        rendered = render_doctor_markdown({"typescript_control_plane": readiness})
        assert "typescript_runtime_locator_state: `invalid`" in rendered
        assert "typescript_runtime_recorded_pid_alive: `True`" in rendered

        restarted = effect_runtime.restart_effect_runtime(wait_for_exit=True)
        assert restarted["status"] == "stopped"
        assert effect_runtime._pid_is_alive(first["pid"]) is False
    finally:
        _shutdown_info(original)
        if info_path.exists():
            try:
                replacement = json.loads(info_path.read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError):
                replacement = None
            if isinstance(replacement, dict):
                _shutdown_info(replacement)


def test_unreadable_locator_reports_a_diagnostic_instead_of_looking_absent(
    tmp_path: Path,
    monkeypatch,
) -> None:
    _isolate_runtime(tmp_path, monkeypatch)
    info_path = _runtime_info_path()
    info_path.parent.mkdir(parents=True)
    info_path.write_text("not-json", encoding="utf-8")

    readiness = effect_runtime.collect_effect_runtime_readiness()

    lifecycle = readiness["runtime_lifecycle"]
    assert lifecycle["state"] == "stopped"
    assert lifecycle["locator_state"] == "invalid"
    assert lifecycle["recorded_pid_alive"] is None
    assert lifecycle["diagnostic_code"] == "runtime_locator_unreadable"


def test_invalid_utf8_locator_does_not_break_doctor(
    tmp_path: Path,
    monkeypatch,
) -> None:
    _isolate_runtime(tmp_path, monkeypatch)
    info_path = _runtime_info_path()
    info_path.parent.mkdir(parents=True)
    info_path.write_bytes(b"\xff\xfe\x00not-a-locator")

    readiness = effect_runtime.collect_effect_runtime_readiness()

    lifecycle = readiness["runtime_lifecycle"]
    assert lifecycle["state"] == "stopped"
    assert lifecycle["locator_state"] == "invalid"
    assert lifecycle["recorded_pid_alive"] is None
    assert lifecycle["diagnostic_code"] == "runtime_locator_unreadable"
    rendered = render_doctor_markdown({"typescript_control_plane": readiness})
    assert "typescript_runtime_locator_state: `invalid`" in rendered
    assert "typescript_runtime_diagnostic: `runtime_locator_unreadable`" in rendered


def test_dead_recorded_pid_keeps_a_liveness_diagnostic(
    tmp_path: Path,
    monkeypatch,
) -> None:
    _isolate_runtime(tmp_path, monkeypatch)
    process = subprocess.Popen([sys.executable, "-c", "pass"])
    dead_pid = process.pid
    process.wait(timeout=10)
    assert effect_runtime._pid_is_alive(dead_pid) is False

    info_path = _runtime_info_path()
    info_path.parent.mkdir(parents=True)
    info_path.write_text(
        json.dumps(
            {
                "schema_version": effect_runtime.EFFECT_RUNTIME_INFO_SCHEMA_VERSION,
                "fingerprint": effect_runtime._runtime_fingerprint(),
                "pid": dead_pid,
                "host": "127.0.0.1",
                "port": 1,
                "token": "stale-token",
            }
        ),
        encoding="utf-8",
    )

    readiness = effect_runtime.collect_effect_runtime_readiness()

    lifecycle = readiness["runtime_lifecycle"]
    assert lifecycle["state"] == "stopped"
    assert lifecycle["locator_state"] == "invalid"
    assert lifecycle["recorded_pid_alive"] is False
    assert lifecycle["diagnostic_code"] == "runtime_locator_pid_not_alive"
