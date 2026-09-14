from copy import deepcopy

import pytest
from fastapi.testclient import TestClient
from pydantic import ValidationError
from strands import ToolContext

from imhungry.api import create_app
from imhungry.errors import AppError, NotFound
from imhungry.models import EstimatedNutrition
from imhungry.providers import BedrockNutritionProvider
from imhungry.tools import TOOLS
from test_services import FOOD, PROFILE, service
from test_repository import repo

RECIPE = {"name": "Yogurt bowl", "yield": {"servings": 2}, "ingredients": [
    {"name": "Yogurt", "quantity": 2, "unit": "cups", "nutrition_for_quantity": FOOD["nutrition"], "source": FOOD["source"]}]}
SAVED = {"name": "Usual yogurt", "default_serving": {"quantity": 1, "unit": "cup"}, "nutrition_per_serving": FOOD["nutrition"], "source": FOOD["source"]}
HYDRATION = {"consumed_at": FOOD["consumed_at"], "amount_ml": 500}
PLAN = {"scheduled_at": FOOD["consumed_at"], "meal_slot": "dinner", "context": {"type": "social_event", "event_description": "Dinner with friends"},
        "items": [{"name": "Rice bowl", "serving_description": "one bowl"}], "alternatives": [{"name": "Vegetables", "reason": "Adds variety"}]}
CHECKIN = {"recorded_at": FOOD["consumed_at"], "measurements": {"weight_kg": 80}, "subjective": {"hunger": 6, "energy": 7, "recovery": 5, "food_fixation": 4}}
PATTERN = {"category": "nighttime_snacking", "description": "Hungry before bed", "user_confirmed": True, "strategies": [{"type": "portioning", "description": "Prepare a satisfying snack"}]}
SAMPLES = {"recipes": RECIPE, "saved-foods": SAVED, "hydration": HYDRATION, "planned-meals": PLAN, "check-ins": CHECKIN, "behavior-patterns": PATTERN}


@pytest.mark.parametrize("kind", list(SAMPLES))
def test_resource_http_lifecycle_and_isolation(service, kind):
    client = TestClient(create_app(service, verifier=lambda token: token))
    headers = {"Authorization": "Bearer alice", "Idempotency-Key": kind}
    url = "/v1/" + kind
    response = client.post(url, headers=headers, json=SAMPLES[kind])
    assert response.status_code == 201, response.text
    item = response.json()
    assert client.post(url, headers=headers, json=SAMPLES[kind]).json() == item
    owned_url = url + "/" + item["entry_ref"]
    assert client.get(owned_url, headers={"Authorization": "Bearer bob"}).status_code == 404
    assert client.get(url, headers=headers).json()["items"] == [item]
    patch = {"name": "Edited"} if kind in {"recipes", "saved-foods"} else {"notes": "Edited"} if kind in {"hydration", "check-ins"} else {"status": "skipped" if kind == "planned-meals" else "resolved"}
    updated = client.patch(owned_url, headers={**headers, "If-Match": "1"}, json=patch)
    assert updated.status_code == 200, updated.text
    assert updated.json()["version"] == 2
    assert client.delete(owned_url, headers={**headers, "If-Match": "2"}).status_code == 200
    assert client.get(owned_url, headers=headers).status_code == 404


def test_recipe_arithmetic_and_historical_intake(service):
    recipe = service.create("alice", "recipes", RECIPE, "recipe")
    assert recipe["nutrition_per_serving"]["energy_kcal"] == 75
    intake = service.create("alice", "food-log", {**FOOD, "nutrition": recipe["nutrition_per_serving"], "source": {"type": "recipe", "recipe_id": recipe["recipe_id"]}}, "log")
    service.update("alice", "recipes", recipe["recipe_id"], {"yield": {"servings": 1}}, 1)
    assert service.get("alice", "food-log", intake["entry_ref"])["nutrition"]["energy_kcal"] == 75
    with pytest.raises(ValidationError):
        service.calculate_recipe({**RECIPE, "yield": {"servings": 0}})


def test_hydration_frequency_and_context(service):
    service.update("alice", "profile", "profile", PROFILE, 0)
    a = service.create("alice", "food-log", FOOD, "a")
    service.create("alice", "food-log", FOOD, "b")
    assert service.frequent_foods("alice")[0]["count"] == 2
    service.delete("alice", "food-log", a["entry_ref"], 1)
    assert service.frequent_foods("alice")[0]["count"] == 1
    drink = service.create("alice", "hydration", HYDRATION, "drink")
    assert service.hydration_summary("alice", "2026-09-14")["total_ml"] == 500
    service.update("alice", "hydration", drink["entry_ref"], {"consumed_at": "2026-09-15T13:00:00Z"}, 1)
    assert service.hydration_summary("alice", "2026-09-14")["total_ml"] == 0
    service.create("alice", "planned-meals", PLAN, "plan")
    context = service.meal_context("alice", "2026-09-14")
    assert context["profile"]["allergies"] == ["peanuts"]
    assert context["planned_meals"][0]["context"]["type"] == "social_event"
    assert context["nutrition"]["totals"]["energy_kcal"] == 150


def test_progress_skips_weightless_checkins_and_preserves_confirmation(service):
    service.create("alice", "check-ins", CHECKIN, "weight")
    service.create("alice", "check-ins", {"recorded_at": "2026-09-14T17:00:00Z", "subjective": {"body_image_note": "Discouraged today", "hunger": 8}}, "feelings")
    service.create("alice", "behavior-patterns", PATTERN, "confirmed")
    result = service.progress("alice", "2026-09-13", "2026-09-14")
    assert result["latest_weight"]["weight_kg"] == 80
    assert result["subjective_trends"]["hunger"]["average"] == 7
    assert result["adherence"]["distribution"]["unknown"] == 2
    assert result["behavior_patterns"][0]["user_confirmed"] is True
    with pytest.raises(ValidationError):
        service.create("alice", "behavior-patterns", {**PATTERN, "user_confirmed": False}, "unconfirmed")


def test_planned_meal_links_only_owned_consumption(service):
    food = service.create("alice", "food-log", FOOD, "eaten")
    with pytest.raises(NotFound):
        service.create("bob", "planned-meals", {**PLAN, "completed_intake_entry_ids": [food["entry_id"]]}, "stolen")
    service.create("alice", "planned-meals", {**PLAN, "status": "completed", "completed_intake_entry_ids": [food["entry_id"]]}, "accepted")
    assert len(service.records("alice", "food-log", "2026-09-14")) == 1


def estimate_result():
    return {"food": FOOD["food"], "nutrition": FOOD["nutrition"], "source": {"type": "model_estimate"},
            "estimate": {"confidence": "medium", "ranges": {"energy_kcal": {"minimum": 120, "maximum": 180}}, "assumptions": ["Typical plain yogurt"]}}


def test_provider_estimation_and_unavailable_contract(service):
    fallback = service.restaurant_menu("alice", "Known restaurant")
    assert fallback["status"] == "unavailable"
    assert fallback["fallback"]["tool"] == "estimate_food_nutrition"
    class Model:
        async def structured_output(self, output_model, prompt, system_prompt=None):
            assert "entire described quantity" in system_prompt
            yield {"output": output_model.model_validate(estimate_result())}
    service.provider = BedrockNutritionProvider(Model)
    request = {"description": "Yogurt", "quantity": 1, "unit": "cup", "known_nutrition": {"protein_g": 20}}
    result = service.estimate_food("alice", request)
    assert result["estimate"]["confidence"] == "medium"
    assert service.records("alice", "food-log", "2026-09-14") == []
    with pytest.raises(AppError):
        service.estimate_food("alice", {**request, "known_nutrition": {"protein_g": 99}})
    with pytest.raises(AppError):
        service.lookup_food("alice", {"query": "yogurt"})
    client = TestClient(create_app(service, verifier=lambda token: token))
    response = client.get("/v1/restaurant-menus/search?restaurant_name=Known", headers={"Authorization": "Bearer alice"})
    assert response.status_code == 200
    assert response.json()["fallback"]["tool"] == "estimate_food_nutrition"


def test_all_feature_write_tools_use_shared_services(service):
    tool_map = {tool.tool_name: tool for tool in TOOLS}
    from imhungry.models import RECORDS
    for index, (name, kind, argument) in enumerate([
        ("save_recipe", "recipes", "recipe"), ("save_food", "saved-foods", "food"),
        ("log_hydration", "hydration", "entry"), ("save_planned_meal", "planned-meals", "meal"),
        ("log_checkin", "check-ins", "checkin"), ("save_behavior_pattern", "behavior-patterns", "pattern")]):
        ctx = ToolContext(tool_use={"toolUseId": str(index), "name": name, "input": {}}, agent=None,
                          invocation_state={"user_id": "alice", "services": service, "request_id": "request"})
        result = tool_map[name](tool_context=ctx, **{argument: RECORDS[kind][1].model_validate(SAMPLES[kind])})
        assert result.get("version") == 1, result
        assert service.get("alice", kind, result["entry_ref"]) == result
