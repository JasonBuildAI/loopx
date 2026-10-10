#!/usr/bin/env python3
"""Pin a Claude Code entry script's own stdio to UTF-8.

Claude Code pipes UTF-8 across both stdio boundaries of this plugin: the session
/ tool-event JSON on stdin, and the hook decision or statusline segment on
stdout. ``sys.stdin`` / ``sys.stdout`` default to the host locale codec instead -
``cp936`` on a zh-CN Windows host. There, ``goal_policy.py`` decodes a non-ASCII
event into mojibake, so ``active_context`` misses the project goal and the hook
emits ``{}``: the should_run / write_scope gate silently fails OPEN for every
tool. ``goal_status.py`` cannot encode the glyphs of its own segment and degrades
to a bare ``[loopx <goal>]``.

``loopx/entrypoint.py`` pins the same streams for the shipped CLI; these two
scripts are launched directly by Claude Code, outside that entrypoint, so they
pin their own. Input stays strict, so a malformed event is refused instead of
being repaired into a valid one; output falls back to ``replace`` so an
unencodable character cannot abort an already-computed decision.
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
