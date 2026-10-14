"""The local producer of `peer_agent_directory_v0` is bounded and non-mutating."""

from __future__ import annotations

import contextlib
import io
import json

import pytest

from loopx.cli import main as cli_main
from loopx.control_plane.agents.management_projection import (
    build_agent_management_projection,
    projected_agent_goals,
    projected_agent_ids,
)
from loopx.control_plane.agents.directory import (
    GAP_AUDIENCE_NOT_AUTHORIZED,
    LIMITATION_CALLER_IDENTITY_NOT_SUPPLIED,
    LIMITATION_LEASE_STATE_NOT_PROJECTED,
    LIMITATION_PRESENCE_PROVIDER_UNAVAILABLE,
    LIMITATION_ROUTE_CANDIDATE_WITHHELD,
    LIMITATION_ROWS_TRUNCATED,
    MAX_DIRECTORY_ROWS,
    MAX_ROUTE_CANDIDATES,
    PEER_AGENT_DIRECTORY_SCHEMA_VERSION,
    build_peer_agent_directory,
)
from loopx.control_plane.runtime.public_safety import (
    validate_public_safe_value,
)


GOAL_ID = "peer-directory-fixture"
WORKING_AGENT = "agent-working"
IDLE_AGENT = "agent-idle"
STALE_AGENT = "agent-stale"
SUSPECTED_STALE_AT = "2020-01-01T00:00:00+08:00"


def _status_payload(agent_ids: list[str] | None = None) -> dict[str, object]:
    registered = agent_ids or [WORKING_AGENT, IDLE_AGENT, STALE_AGENT]
    return {
        "goal_filter": GOAL_ID,
        "run_history": {
            "goals": [
                {
                    "id": GOAL_ID,
                    "coordination": {"registered_agents": registered},
                }
            ]
        },
        "todo_index": {
            "items": [
                {
                    "role": "agent",
                    "todo_id": "todo_directory_blocked",
                    "goal_id": GOAL_ID,
                    "status": "blocked",
                    "priority": "P1",
                    "task_class": "advancement_task",
                    "action_kind": "implement",
                    "claimed_by": WORKING_AGENT,
                    "updated_at": SUSPECTED_STALE_AT,
                    "text": "Finish the bounded directory producer.",
                },
                {
                    "role": "agent",
                    "todo_id": "todo_directory_open",
                    "goal_id": GOAL_ID,
                    "status": "open",
                    "priority": "P2",
                    "task_class": "advancement_task",
                    "action_kind": "validate",
                    "claimed_by": STALE_AGENT,
                    "updated_at": SUSPECTED_STALE_AT,
                    "text": "Validate the directory packet against the contract.",
                },
            ]
        },
    }


def _rows_by_agent(packet: dict[str, object]) -> dict[str, dict[str, object]]:
    return {str(row["agent_id"]): row for row in packet["rows"]}  # type: ignore[index]


def test_directory_reports_registered_agents_without_inventing_presence() -> None:
    packet = build_peer_agent_directory(_status_payload(), caller_agent_id=WORKING_AGENT)

    assert packet["schema_version"] == PEER_AGENT_DIRECTORY_SCHEMA_VERSION
    assert packet["goal_id"] == GOAL_ID
    assert packet["scope"]["caller_membership"] == "registered_agent"  # type: ignore[index]
    assert packet["scope"]["gaps"] == []  # type: ignore[index]

    rows = _rows_by_agent(packet)
    assert set(rows) == {WORKING_AGENT, IDLE_AGENT, STALE_AGENT}
    # An Agent with no projected work still gets a row: identity is the registry's,
    # not the work item's.
    assert rows[IDLE_AGENT]["work"] is None
    working = rows[WORKING_AGENT]["work"]
    assert working["todo_id"] == "todo_directory_blocked"
    assert working["todo_status"] == "blocked"
    assert working["claimed"] is True
    assert working["claimed_by"] == WORKING_AGENT
    assert working["claim_age_state"] == "suspected_stale"
    # No provider is registered, so the packet names the gap instead of implying
    # that a registered Agent is running or stopped.
    assert "presence" not in rows[WORKING_AGENT]
    assert packet["presence_coverage"]["state"] == "unavailable"  # type: ignore[index]
    assert LIMITATION_PRESENCE_PROVIDER_UNAVAILABLE in packet["limitations"]  # type: ignore[operator]
    assert LIMITATION_LEASE_STATE_NOT_PROJECTED in packet["limitations"]  # type: ignore[operator]
    # Observation and delivery grant nothing.
    assert packet["authority"]["writes"] is False  # type: ignore[index]
    assert packet["authority"]["observation_grants"] == []  # type: ignore[index]


def test_rollup_orders_typed_attention_and_assigns_nothing() -> None:
    packet = build_peer_agent_directory(_status_payload())

    rollup = packet["rollup"]
    assert rollup["basis"] == "typed_work_state_only"
    assert rollup["assigns_work"] is False
    assert rollup["needs_decision"] == [WORKING_AGENT]
    # Row order is the projection's; the rollup adds no ranking of its own.
    assert set(rollup["stale_claims"]) == {WORKING_AGENT, STALE_AGENT}
    assert rollup["without_claim"] == [IDLE_AGENT]
    assert rollup["counts"] == {
        "needs_decision": 1,
        "stale_claims": 2,
        "without_claim": 1,
    }


def test_unregistered_caller_gets_a_scope_gap_instead_of_rows() -> None:
    packet = build_peer_agent_directory(_status_payload(), caller_agent_id="agent-outsider")

    assert packet["rows"] == []
    assert packet["row_count"] == 0
    gaps = packet["scope"]["gaps"]  # type: ignore[index]
    assert [gap["kind"] for gap in gaps] == [GAP_AUDIENCE_NOT_AUTHORIZED]
    assert gaps[0]["caller_agent_id"] == "agent-outsider"


def test_missing_caller_identity_is_declared_not_invented() -> None:
    packet = build_peer_agent_directory(_status_payload())

    assert packet["scope"]["caller_agent_id"] is None  # type: ignore[index]
    assert packet["scope"]["caller_membership"] == "local_surface"  # type: ignore[index]
    assert LIMITATION_CALLER_IDENTITY_NOT_SUPPLIED in packet["limitations"]  # type: ignore[operator]
    assert packet["row_count"] == 3


def test_truncated_directory_declares_the_rows_it_omitted() -> None:
    registered = [f"agent-{index:02d}" for index in range(MAX_DIRECTORY_ROWS + 2)]

    packet = build_peer_agent_directory(_status_payload(registered))

    # The projection's registered count is the union of declared registrations
    # and the Agents that claim projected work, so the invariant is checked
    # against that count rather than the fixture list.
    assert packet["registered_agent_count"] > len(registered)
    assert packet["row_count"] == MAX_DIRECTORY_ROWS
    assert (
        packet["row_count"] + packet["omitted_row_count"]
        == packet["registered_agent_count"]
    )
    assert packet["omitted_row_count"] > 0
    assert LIMITATION_ROWS_TRUNCATED in packet["limitations"]  # type: ignore[operator]


def test_projection_pages_past_its_display_cap_and_reports_the_page_span() -> None:
    """The cap bounds the published rows, never the registry a caller may read."""

    registered = [f"agent-{index:02d}" for index in range(MAX_DIRECTORY_ROWS + 4)]
    payload = _status_payload(registered)
    expected_order = sorted(set(registered) | {WORKING_AGENT, STALE_AGENT})
    cursor = expected_order[MAX_DIRECTORY_ROWS - 1]

    full = build_agent_management_projection(payload)
    assert len(full["agents"]) == MAX_DIRECTORY_ROWS
    # The full set is what scope questions read; only the rows are capped.
    assert projected_agent_ids(payload) == set(expected_order)
    assert "selected_agent_count" not in full["source_summary"]

    page = build_agent_management_projection(payload, after_agent_id=cursor)
    assert [row["agent_id"] for row in page["agents"]] == expected_order[MAX_DIRECTORY_ROWS:]
    assert page["source_summary"]["selected_agent_count"] == (
        len(expected_order) - MAX_DIRECTORY_ROWS
    )
    assert page["source_summary"]["registered_agent_count"] == len(expected_order)


def test_capped_directory_completes_by_following_next_cursor() -> None:
    registered = [f"agent-{index:02d}" for index in range(MAX_DIRECTORY_ROWS + 4)]
    payload = _status_payload(registered)
    expected_order = sorted(set(registered) | {WORKING_AGENT, STALE_AGENT})

    first = build_peer_agent_directory(payload, caller_agent_id=WORKING_AGENT)
    first_ids = [row["agent_id"] for row in first["rows"]]
    assert first_ids == expected_order[:MAX_DIRECTORY_ROWS]
    assert first["cursor"] is None
    assert first["next_cursor"] == expected_order[MAX_DIRECTORY_ROWS - 1]
    assert (
        first["row_count"] + first["omitted_row_count"]
        == first["registered_agent_count"]
    )

    second = build_peer_agent_directory(
        payload, caller_agent_id=WORKING_AGENT, cursor=first["next_cursor"]
    )
    second_ids = [row["agent_id"] for row in second["rows"]]
    assert second["cursor"] == first["next_cursor"]
    assert second_ids == expected_order[MAX_DIRECTORY_ROWS:]
    assert second["next_cursor"] is None
    assert len(first_ids + second_ids) == len(set(first_ids + second_ids))
    assert len(first_ids + second_ids) == first["registered_agent_count"]
    assert (
        second["row_count"] + second["omitted_row_count"]
        == second["registered_agent_count"]
    )


def test_registered_caller_beyond_the_first_page_keeps_its_scope() -> None:
    """Membership is the registry, not the page: the cap cannot deny a caller."""

    registered = [f"agent-{index:02d}" for index in range(MAX_DIRECTORY_ROWS + 1)]
    payload = _status_payload(registered)
    expected_order = sorted(set(registered) | {WORKING_AGENT, STALE_AGENT})

    beyond = build_peer_agent_directory(
        payload, caller_agent_id=expected_order[MAX_DIRECTORY_ROWS]
    )
    assert beyond["scope"]["gaps"] == []  # type: ignore[index]
    assert beyond["scope"]["caller_membership"] == "registered_agent"  # type: ignore[index]

    # A caller placed before the cursor is not on the page it reads, and still
    # must not be told it is unregistered.
    later = build_peer_agent_directory(
        payload,
        caller_agent_id="agent-00",
        cursor=expected_order[MAX_DIRECTORY_ROWS - 1],
    )
    assert later["scope"]["gaps"] == []  # type: ignore[index]
    assert "agent-00" not in [row["agent_id"] for row in later["rows"]]


def test_cursor_is_a_position_and_an_empty_page_is_declared_not_erased() -> None:
    payload = _status_payload()

    positioned = build_peer_agent_directory(
        payload, caller_agent_id=WORKING_AGENT, cursor="agent-j"
    )
    assert [row["agent_id"] for row in positioned["rows"]] == [
        STALE_AGENT,
        WORKING_AGENT,
    ]
    assert positioned["cursor"] == "agent-j"
    assert positioned["next_cursor"] is None
    assert positioned["scope"]["gaps"] == []  # type: ignore[index]

    beyond = build_peer_agent_directory(
        payload, caller_agent_id=WORKING_AGENT, cursor="zzz-after-the-last-id"
    )
    assert beyond["rows"] == []
    assert beyond["row_count"] == 0
    assert beyond["cursor"] == "zzz-after-the-last-id"
    assert beyond["next_cursor"] is None
    assert beyond["scope"]["gaps"] == []  # type: ignore[index]
    assert beyond["registered_agent_count"] == 3
    assert LIMITATION_ROWS_TRUNCATED in beyond["limitations"]  # type: ignore[operator]


def test_a_cursor_that_cannot_be_published_is_rejected_not_echoed() -> None:
    with pytest.raises(ValueError):
        build_peer_agent_directory(
            _status_payload(),
            cursor="ghp_" + "1234567890abcdefghijklmnopqrstuvwxyz1234",
        )


def test_cli_agent_directory_continues_with_cursor(tmp_path) -> None:
    registered = [f"agent-{index:02d}" for index in range(MAX_DIRECTORY_ROWS + 4)]
    registry = tmp_path / "registry.json"
    registry.write_text(
        json.dumps(
            {
                "schema_version": "0.1",
                "goals": [
                    {"id": GOAL_ID, "coordination": {"registered_agents": registered}}
                ],
            }
        )
        + "\n",
        encoding="utf-8",
    )

    def run(*extra: str) -> dict[str, object]:
        output = io.StringIO()
        with contextlib.redirect_stdout(output):
            exit_code = cli_main(
                [
                    "--registry",
                    str(registry),
                    "--format",
                    "json",
                    "agent-directory",
                    "--goal-id",
                    GOAL_ID,
                    "--agent-id",
                    registered[0],
                    "--scan-path",
                    str(tmp_path),
                    *extra,
                ]
            )
        assert exit_code == 0
        return json.loads(output.getvalue())

    first = run()
    assert first["row_count"] == MAX_DIRECTORY_ROWS
    assert first["next_cursor"]

    second = run("--cursor", str(first["next_cursor"]))
    ids = [row["agent_id"] for row in first["rows"]] + [  # type: ignore[index]
        row["agent_id"] for row in second["rows"]  # type: ignore[index]
    ]
    assert sorted(ids) == registered
    assert len(ids) == len(set(ids))
    assert second["next_cursor"] is None


def test_rows_report_a_peer_route_without_selecting_one() -> None:
    payload = _status_payload()
    coordination = payload["run_history"]["goals"][0]["coordination"]
    coordination["thread_agent_bindings"] = [
        {
            "agent_id": WORKING_AGENT,
            "thread_id": "thread-app",
            "host_surface": "codex-app",
        },
        {
            "agent_id": WORKING_AGENT,
            "thread_id": "thread-cli",
            "host_surface": "codex-cli",
        },
    ]

    packet = build_peer_agent_directory(payload, caller_agent_id=WORKING_AGENT)
    rows = _rows_by_agent(packet)

    assert rows[WORKING_AGENT]["peer_route"]["outcome"] == "multiple_candidates"
    assert rows[WORKING_AGENT]["peer_route"]["candidate_count"] == 2
    assert rows[WORKING_AGENT]["peer_route"]["candidates"] == [
        {"thread_id": "thread-app", "host_surface": "codex-app"},
        {"thread_id": "thread-cli", "host_surface": "codex-cli"},
    ]
    assert rows[IDLE_AGENT]["peer_route"]["outcome"] == "no_candidate"
    assert rows[IDLE_AGENT]["peer_route"]["candidates"] == []
    # A route is a locator: it must not read as membership, presence or a lease.
    assert packet["scope"]["caller_membership"] == "registered_agent"
    assert LIMITATION_LEASE_STATE_NOT_PROJECTED in packet["limitations"]


def test_a_credential_shaped_candidate_is_withheld_not_erased() -> None:
    """Publication filters, it does not delete: the count keeps the truth."""

    payload = _status_payload()
    payload["run_history"]["goals"][0]["coordination"]["thread_agent_bindings"] = [
        {
            "agent_id": WORKING_AGENT,
            "thread_id": "ghp_" + "1234567890abcdefghijklmnopqrstuvwxyz1234",
            "host_surface": "codex-app",
        },
        {
            "agent_id": WORKING_AGENT,
            "thread_id": "thread-visible",
            "host_surface": "codex-app",
        },
    ]

    packet = build_peer_agent_directory(payload, caller_agent_id=WORKING_AGENT)
    route = _rows_by_agent(packet)[WORKING_AGENT]["peer_route"]

    assert route["candidate_count"] == 2
    assert route["candidates"] == [
        {"thread_id": "thread-visible", "host_surface": "codex-app"}
    ]
    assert route["withheld_candidate_count"] == 1
    assert LIMITATION_ROUTE_CANDIDATE_WITHHELD in packet["limitations"]
    validate_public_safe_value(packet, path="peer_agent_directory")


def test_the_published_candidate_list_respects_its_budget() -> None:
    payload = _status_payload()
    payload["run_history"]["goals"][0]["coordination"]["thread_agent_bindings"] = [
        {
            "agent_id": WORKING_AGENT,
            "thread_id": f"thread-{index}",
            "host_surface": "codex-app",
        }
        for index in range(5)
    ]

    packet = build_peer_agent_directory(payload, caller_agent_id=WORKING_AGENT)
    route = _rows_by_agent(packet)[WORKING_AGENT]["peer_route"]

    assert route["candidate_count"] == 5
    assert len(route["candidates"]) == MAX_ROUTE_CANDIDATES
    assert [item["thread_id"] for item in route["candidates"]] == [
        "thread-0",
        "thread-1",
        "thread-2",
    ]
    assert "withheld_candidate_count" not in route


@pytest.mark.parametrize("status", ["blocked", "deferred", "done"])
def test_canonical_identity_wins_over_stale_display_variants(status: str) -> None:
    payload = _status_payload([WORKING_AGENT])
    current = dict(payload["todo_index"]["items"][0], status=status, done=status in ("deferred", "done"))
    stale = dict(current, status="open", done=False, index=99,
        text="Old shorter display", selected_by="current_agent_claimed_todo")
    payload["attention_queue"] = {"items": [{"goal_id": GOAL_ID,
        "agent_todos": {"items": [current], "first_open_items": [stale]},
        "agent_lane_next_action": stale,
        "project_asset": {"agent_todos": {"items": [stale]}}}]}
    payload["todo_index"] = {"items": [dict(stale, source="attention_queue")]}

    management = build_agent_management_projection(payload)
    row = next(row for row in management["agents"] if row["agent_id"] == WORKING_AGENT)
    work = _rows_by_agent(build_peer_agent_directory(payload))[WORKING_AGENT]["work"]
    if status == "done":
        assert "current_todo" not in row
        assert work is None
        assert projected_agent_goals(payload)[GOAL_ID][WORKING_AGENT]["open_todo_ids"] == []
    else:
        assert row["current_todo"]["status"] == status
        assert work["todo_status"] == status


def test_stale_hint_cannot_restore_a_cleared_claim() -> None:
    payload = _status_payload([WORKING_AGENT])
    current = dict(payload["todo_index"]["items"][0])
    current.pop("claimed_by")
    stale = dict(current, claimed_by=WORKING_AGENT, agent_id=WORKING_AGENT)
    payload["attention_queue"] = {"items": [{"goal_id": GOAL_ID,
        "agent_todos": {"items": [current]}, "agent_lane_next_action": stale}]}
    payload["todo_index"] = {"items": []}
    assert _rows_by_agent(build_peer_agent_directory(payload))[WORKING_AGENT]["work"] is None
    assert projected_agent_goals(payload)[GOAL_ID][WORKING_AGENT]["open_todo_ids"] == []


def test_unavailable_source_does_not_resurrect_project_asset_or_hint() -> None:
    payload = _status_payload([WORKING_AGENT])
    stale = payload["todo_index"]["items"][0]
    payload["attention_queue"] = {"items": [{"goal_id": GOAL_ID,
        "todo_source": "unavailable", "agent_lane_next_action": stale,
        "project_asset": {"agent_todos": {"items": [stale]}}}]}
    payload["todo_index"]["items"] = []
    packet = build_peer_agent_directory(payload)
    assert _rows_by_agent(packet)[WORKING_AGENT]["work"] is None
    assert projected_agent_goals(payload)[GOAL_ID][WORKING_AGENT]["open_todo_ids"] == []
