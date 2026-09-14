"""Exercise every registered tool through Strands' validation/execution adapter."""

import json

from strands import ToolContext

from imhungry.providers import run_async
from imhungry.tools import TOOLS
from test_services import service, PROFILE, FOOD, GOAL
from test_repository import repo
from test_features import RECIPE, SAVED, HYDRATION, PLAN, CHECKIN, PATTERN, estimate_result


def test_every_tool_through_sdk_adapter(service):
    class Provider:
        def search(self, request):
            return [{"food": FOOD["food"], "nutrition": FOOD["nutrition"], "source": FOOD["source"]}]
        def menu(self, *args):
            return self.search(None)
        def estimate(self, request):
            return estimate_result()
    service.provider = Provider()
    by_name = {t.tool_name: t for t in TOOLS}
    exercised = set()

    async def flow():
        async def call(name, **arguments):
            exercised.add(name)
            use = {"name": name, "input": arguments, "toolUseId": name}
            state = {"user_id": "alice", "services": service, "request_id": "contract-test"}
            ctx = ToolContext(tool_use=use, agent=None, invocation_state=state)
            events = [event async for event in by_name[name].stream(use, state, _tool_context=ctx)]
            result = events[-1]["tool_result"]
            assert result["status"] == "success", result
            data = json.loads(result["content"][0]["text"])
            assert "error" not in data, (name, data)
            assert "PK" not in data and "SK" not in data
            return data

        await call("update_user_profile", patch=PROFILE, expected_version=0)
        assert (await call("get_user_profile"))["allergies"] == ["peanuts"]
        calculation = await call("calculate_nutrition_strategy", request=GOAL)
        await call("save_nutrition_strategy", strategy={**{k: calculation[k] for k in ["goal", "targets", "calculation"]},
                                                      "effective_from": "2026-09-14T05:00:00Z", "change_reason": "setup"})
        assert (await call("get_nutrition_strategy"))["strategy"]
        food = await call("log_food", entry=FOOD)
        assert (await call("get_food_log", start_date="2026-09-14"))["items"]
        assert (await call("get_nutrition_summary", start_date="2026-09-14"))["totals"]["energy_kcal"] == 150
        edited = await call("edit_food", entry_ref=food["entry_ref"], patch={"notes": "Corrected"}, expected_version=1)
        await call("calculate_recipe_nutrition", request=RECIPE)
        recipe = await call("save_recipe", recipe=RECIPE)
        await call("update_recipe", entry_ref=recipe["entry_ref"], patch={"yield": {"servings": 1}}, expected_version=1)
        assert (await call("get_recipes"))["items"][0]["nutrition_per_serving"]["energy_kcal"] == 150
        await call("save_food", food=SAVED)
        assert (await call("get_saved_and_frequent_foods"))["frequent_foods"][0]["count"] == 1
        hydration = await call("log_hydration", entry=HYDRATION)
        await call("edit_hydration", entry_ref=hydration["entry_ref"], patch={"amount_ml": 600}, expected_version=1)
        assert (await call("get_hydration_summary", start_date="2026-09-14"))["total_ml"] == 600
        plan = await call("save_planned_meal", meal=PLAN)
        await call("update_planned_meal", entry_ref=plan["entry_ref"], patch={"status": "skipped"}, expected_version=1)
        assert (await call("get_planned_meals", start_date="2026-09-14"))["items"][0]["status"] == "skipped"
        assert (await call("get_meal_decision_context", local_date="2026-09-14"))["profile"]["allergies"] == ["peanuts"]
        checkin = await call("log_checkin", checkin=CHECKIN)
        await call("update_checkin", entry_ref=checkin["entry_ref"], patch={"subjective": {"hunger": 7}}, expected_version=1)
        pattern = await call("save_behavior_pattern", pattern=PATTERN)
        await call("update_behavior_pattern", entry_ref=pattern["entry_ref"], patch={"status": "active"}, expected_version=1)
        assert (await call("get_behavior_patterns"))["items"]
        assert (await call("get_progress_context", start_date="2026-09-14", end_date="2026-09-14"))["subjective_trends"]["hunger"]["average"] == 7
        assert (await call("lookup_food_nutrition", request={"query": "yogurt"}))["items"]
        assert (await call("estimate_food_nutrition", request={"description": "yogurt", "quantity": 1, "unit": "cup"}))["estimate"]
        assert (await call("lookup_restaurant_menu", restaurant_name="Known restaurant"))["items"]
        await call("remove_hydration", entry_ref=hydration["entry_ref"], expected_version=2)
        await call("remove_planned_meal", entry_ref=plan["entry_ref"], expected_version=2)
        await call("remove_food", entry_ref=edited["entry_ref"], expected_version=2)
        assert exercised == set(by_name)
    run_async(flow)
