#!/usr/bin/env python3
"""Pin a Claude Code entry script's own stdio to UTF-8.

Claude Code pipes UTF-8 across every stdio boundary of this plugin: the session /
tool-event JSON on stdin, and the hook decision, the statusline segment or the
``/loopx`` output on stdout. ``sys.stdin`` / ``sys.stdout`` default to the host
locale codec instead - ``cp936`` on a zh-CN Windows host. There, a non-ASCII
event decodes into mojibake, so ``active_context`` misses the project goal and
``goal_policy.py`` emits ``{}``: the should_run / write_scope gate silently fails
OPEN for every tool. The statusline and ``goalmode_cmd.py`` lose their own
segment instead, because ``▶`` / ``⏸`` / ``⚠`` are not encodable in ``gbk`` - a
non-ASCII session path no longer resolves to a goal (the statusline prints
nothing) and the state line of ``/loopx status`` raises ``UnicodeEncodeError``.

These scripts are launched directly by Claude Code, outside
``loopx/entrypoint.py``, and reach this module through the hooks directory that
is already on their ``sys.path``. That CLI entrypoint pins the same streams for
the shipped CLI with the same policy - skip a stream that already reports UTF-8,
strict stdin, ``replace`` output - deliberately kept as a separate
implementation so a plugin hook never depends on the CLI bootstrap; change both
together. Input stays strict so a non-UTF-8 byte is never repaired into a
different event; output falls back to ``replace`` so an unencodable character
cannot abort an already-computed answer.
"""
from __future__ import annotations

import sys


def pin_utf8_stdio() -> None:
    """Reconfigure stdin/stdout/stderr to UTF-8 unless they already are."""

    for stream in (sys.stdin, sys.stdout, sys.stderr):
        reconfigure = getattr(stream, "reconfigure", None)
        if reconfigure is None:
            continue
        if str(getattr(stream, "encoding", "") or "").lower().replace("_", "-") == "utf-8":
            continue
        errors = "strict" if stream is sys.stdin else "replace"
        try:
            reconfigure(encoding="utf-8", errors=errors)
        except (OSError, ValueError):
            continue
