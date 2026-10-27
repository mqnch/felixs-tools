"""Planner emits plans that validate. No model is involved — Router is a stub."""

from __future__ import annotations

from pathlib import Path

from common import SCHEMA_VERSION, QueryPlan
from logger import Logger, validate_plan
from logger.planner import _plan_from_content, fallback_plan


def test_fallback_plan_is_valid_and_keyword_driven() -> None:
    plan = fallback_plan("find payment timeouts in checkout")
    assert validate_plan(plan).ok
    assert plan.version == SCHEMA_VERSION


def test_fallback_plan_for_an_empty_question_is_still_valid() -> None:
    plan = fallback_plan("")
    assert validate_plan(plan).ok
    assert plan.queries[0].where is None


def test_legacy_router_stub_shape_is_adapted_to_the_frozen_dsl() -> None:
    """The Router stub still emits the slice-001 plan shape; Router is not ours to change."""
    legacy = '{"queries":[{"filters":{"severity":"error"},"terms":["payment"],"limit":25}]}'
    plan = _plan_from_content(legacy)
    assert isinstance(plan, QueryPlan)
    assert validate_plan(plan).ok
    assert plan.queries[0].limit == 25


def test_unparseable_router_output_yields_no_plan() -> None:
    assert _plan_from_content("I could not answer that.") is None


def test_fenced_json_is_unwrapped() -> None:
    content = '```json\n{"queries":[{"where":{"op":"term","value":"timeout"}}]}\n```'
    assert _plan_from_content(content) is not None


def test_planner_always_returns_an_executable_plan(tmp_path: Path) -> None:
    """Whatever Router replies — stub, local model, or garbage — the plan validates."""
    log = Logger(tmp_path / "planner.db")
    try:
        log.ingest_line("ERROR payment failed order=42")
        log.ingest_line("INFO unrelated chatter")
        plan = log.planner.plan("find payment errors")
        assert validate_plan(plan).ok
        assert log.execute_plan(plan).rows_scanned >= 0
    finally:
        log.close()
