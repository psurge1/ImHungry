"""Mock daily nutrition summary tool."""

from __future__ import annotations

from typing import Any

from strands import tool

from .food_log import get_food_log

_MOCK_DAILY_BASELINE = {
    "calories": 1250,
    "protein_g": 82.0,
    "carbs_g": 130.0,
    "fat_g": 42.0,
}


@tool
def get_daily_nutrition_summary() -> dict[str, Any]:
    """Return a mock daily intake summary plus foods logged in this process."""

    logged_foods = get_food_log()
    return {
        "calories": _MOCK_DAILY_BASELINE["calories"]
        + sum(food["calories"] for food in logged_foods),
        "protein_g": _MOCK_DAILY_BASELINE["protein_g"]
        + sum(food["protein_g"] for food in logged_foods),
        "carbs_g": _MOCK_DAILY_BASELINE["carbs_g"]
        + sum(food["carbs_g"] for food in logged_foods),
        "fat_g": _MOCK_DAILY_BASELINE["fat_g"]
        + sum(food["fat_g"] for food in logged_foods),
        "logged_food_count": len(logged_foods),
        "note": "Mock baseline plus foods logged during this process; values are approximate.",
    }
