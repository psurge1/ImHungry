from datetime import datetime, timezone

import pytest
from pydantic import ValidationError
from strands import ToolContext

from imhungry.errors import AppError, Conflict, NotFound
from imhungry.models import Intake
from imhungry.services import NutritionService
from imhungry import tools
from test_repository import repo

NOW = datetime(2026, 9, 14, 18, tzinfo=timezone.utc)
FOOD = {"consumed_at": "2026-09-14T13:00:00Z", "food": {"display_name": "Yogurt", "quantity": 1, "unit": "cup", "serving_description": "one cup"},
        "nutrition": {"energy_kcal": 150, "protein_g": 20, "carbs_g": 10, "fat_g": 3}, "source": {"type": "package_label"}}
PROFILE = {"timezone": "America/Chicago", "height_cm": 178, "date_of_birth": "1995-04-12", "sex_for_bmr_equation": "male", "activity_context": {"level": "moderately_active"}, "allergies": ["peanuts"]}
GOAL = {"goal": {"type": "lose_weight", "baseline_weight_kg": 82.5, "goal_weight_kg": 74, "desired_rate_kg_per_week": .4}}


@pytest.fixture
def service(repo):
    return NutritionService(repo, clock=lambda: NOW)


def test_food_crud_retry_moves_and_isolation(service):
    first = service.create("alice", "food-log", FOOD, "first")
    assert service.create("alice", "food-log", FOOD, "first") == first
    with pytest.raises(Conflict):
        service.create("alice", "food-log", {**FOOD, "notes": "different"}, "first")
    with pytest.raises(NotFound):
        service.get("bob", "food-log", first["entry_ref"])
    patch = {"consumed_at": "2026-09-15T13:00:00Z", "food": {"display_name": "Replacement"}, "nutrition": {"energy_kcal": 200}}
    updated = service.update("alice", "food-log", first["entry_ref"], patch, 1)
    assert updated["entry_id"] == first["entry_id"]
    assert updated["entry_ref"] != first["entry_ref"]
    assert updated["nutrition"]["protein_g"] == 20
    assert service.records("alice", "food-log", "2026-09-14") == []
    assert service.update("alice", "food-log", first["entry_ref"], patch, 1) == updated
    with pytest.raises(Conflict):
        service.update("alice", "food-log", updated["entry_ref"], {"notes": "stale"}, 1)
    assert service.delete("alice", "food-log", updated["entry_ref"], 2)["deleted"]
    assert service.delete("alice", "food-log", updated["entry_ref"], 2)["deleted"]


def test_profile_calculation_and_dated_summary(service):
    assert service.calculate_strategy("alice", GOAL)["complete"] is False
    service.update("alice", "profile", "profile", PROFILE, 0)
    calculated = service.calculate_strategy("alice", GOAL)
    assert calculated["calculation"]["results"] == {"bmr_kcal": 1787.5, "tdee_kcal": 2770.62}
    strategy = {k: calculated[k] for k in ("goal", "targets", "calculation")}
    with pytest.raises(AppError, match="Recalculate"):
        service.create("alice", "nutrition-strategies", {**strategy, "targets": {**strategy["targets"], "energy_kcal": 1},
                       "effective_from": "2026-09-14T05:00:00Z", "change_reason": "forged"}, "forged")
    service.create("alice", "nutrition-strategies", {**strategy, "effective_from": "2026-09-14T05:00:00Z", "change_reason": "setup"}, "strategy")
    with pytest.raises(Conflict):
        service.create("alice", "nutrition-strategies", {**strategy, "effective_from": "2026-09-14T05:00:00Z", "change_reason": "duplicate time"}, "other")
    assert service.current_strategy("alice", "2026-09-13") is None
    service.create("alice", "food-log", FOOD, "food")
    result = service.summary("alice", "2026-09-13", "2026-09-14")
    assert result["logged_days"] == 1
    assert result["averages_per_calendar_day"]["energy_kcal"] == 75
    assert result["days"][0]["targets"] is None
    assert result["days"][1]["remaining"]["protein_g"] == 112
    assert "sodium_mg" not in result["totals"]


def test_timezone_and_cursor_scope(service):
    service.update("alice", "profile", "profile", PROFILE, 0)
    first = service.create("alice", "food-log", {**FOOD, "consumed_at": "2026-09-14T01:00:00Z"}, "midnight")
    assert first["local_date"] == "2026-09-13"
    service.update("alice", "profile", "profile", {"timezone": "Asia/Tokyo"}, 1)
    updated = service.update("alice", "food-log", first["entry_ref"], {"notes": "fixed"}, 1)
    assert updated["local_date"] == "2026-09-13"
    service.create("alice", "food-log", FOOD, "second")
    page = service.list("alice", "food-log", "2026-09-13", "2026-09-14", limit=1)
    assert page["next_cursor"]
    assert len(service.list("alice", "food-log", "2026-09-13", "2026-09-14", cursor=page["next_cursor"])["items"]) == 1
    with pytest.raises(AppError):
        service.list("bob", "food-log", "2026-09-13", "2026-09-14", cursor=page["next_cursor"])


def test_tool_context_and_hidden_identity(service):
    ctx = ToolContext(tool_use={"toolUseId": "t1", "name": "log_food", "input": {}}, agent=None,
                      invocation_state={"services": service, "user_id": "alice", "request_id": "r1"})
    logged = tools.log_food(tool_context=ctx, entry=Intake.model_validate(FOOD))
    assert logged["version"] == 1
    assert tools.get_food_log(tool_context=ctx, start_date="2026-09-14")["items"] == [logged]
    assert "PK" not in str(logged)
    for tool in tools.TOOLS:
        schema = tool.tool_spec["inputSchema"]["json"]
        assert "user_id" not in schema.get("properties", {})
        assert "tool_context" not in schema.get("properties", {})
    ctx.invocation_state = {}
    assert tools.get_user_profile(tool_context=ctx)["error"]["code"] == "identity"


def test_reject_untrusted_patch_and_bad_reference(service):
    with pytest.raises(ValidationError):
        service.update("alice", "profile", "profile", {"user_id": "bob"}, 0)
    with pytest.raises(AppError):
        service.get("alice", "food-log", "../../someone")


def test_future_revision_does_not_change_todays_target(service):
    service.update("alice", "profile", "profile", PROFILE, 0)
    calculation = service.calculate_strategy("alice", GOAL)
    strategy = {k: calculation[k] for k in ("goal", "targets", "calculation")}
    service.create("alice", "nutrition-strategies", {**strategy, "effective_from": "2026-09-14T20:00:00Z", "change_reason": "later"}, "future")
    assert service.summary("alice", "2026-09-14")["days"][0]["targets"] is None
    assert service.summary("alice", "2026-09-15")["days"][0]["targets"] == strategy["targets"]
