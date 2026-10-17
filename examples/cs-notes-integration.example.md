# Sanitized CS-Notes Integration Example

This is a sanitized shape, not a copy of a private local setup.

## Project Files

```text
CS-Notes/
  .local/ACTIVE_GOAL_STATE.md
<<<<<<< HEAD
  .local/LOOPX_REGISTRY.json
=======
  .local/GOAL_HARNESS_REGISTRY.json
>>>>>>> 7dcdc9dc7 (Initial public goal harness scaffold)
  Notes/snippets/codex-goal-pre-tick.py
```

## Pre-Tick Pattern

<<<<<<< HEAD
The project pre-tick reads project-specific state, then adds LoopX
signals:

```bash
loopx --registry .local/LOOPX_REGISTRY.json --format json history
loopx --registry .local/LOOPX_REGISTRY.json --format json check --scan-root Notes/snippets
=======
The project pre-tick reads project-specific state, then adds Goal Harness
signals:

```bash
goal-harness --registry .local/GOAL_HARNESS_REGISTRY.json --format json history
goal-harness --registry .local/GOAL_HARNESS_REGISTRY.json --format json check --scan-root Notes/snippets
>>>>>>> 7dcdc9dc7 (Initial public goal harness scaffold)
```

The returned compact signal can be exposed as:

```json
{
<<<<<<< HEAD
  "loopx_contract_health": {
=======
  "goal_harness_contract_health": {
>>>>>>> 7dcdc9dc7 (Initial public goal harness scaffold)
    "ok": true,
    "errors": 0,
    "warnings": 0,
    "checks": 3
  }
}
```

Keep the real registry and active state private.
