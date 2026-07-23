from felixs_common import LocationId, Preset, RouterRequest, TaskType


def test_location_key_with_service() -> None:
    loc = LocationId(path="src/app.py", service="api")
    assert loc.key() == "api:src/app.py"


def test_location_key_without_service() -> None:
    assert LocationId(path="src/app.py").key() == "src/app.py"


def test_router_request_task_type() -> None:
    req = RouterRequest(
        task_type=TaskType.LOG_QUERY_PLANNING,
        messages=[{"role": "user", "content": "find errors"}],
    )
    assert req.task_type == TaskType.LOG_QUERY_PLANNING


def test_preset_with_alias() -> None:
    preset = Preset.model_validate(
        {
            "name": "ticket-to-pr",
            "steps": [{"id": "scope", "uses": "brain", "with": {"ticket": "T-1"}}],
        }
    )
    assert preset.steps[0].with_["ticket"] == "T-1"
