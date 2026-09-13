"""Tests for the milestone-one local nutrition tools."""

import pytest

from tools.food_log import _clear_food_log, get_food_log, log_food
from tools.nutrition import get_daily_nutrition_summary
from tools.profile import get_user_profile


@pytest.fixture(autouse=True)
def clean_food_log() -> None:
    _clear_food_log()
    yield
    _clear_food_log()


def test_get_user_profile_returns_example_context() -> None:
    profile = get_user_profile()

    assert profile["goal"] == "lose weight gradually while maintaining energy"
    assert profile["height_cm"] == 175
    assert profile["weight_kg"] == 82
    assert profile["activity_level"] == "moderately active"
    assert "high-protein meals" in profile["dietary_preferences"]


def test_log_food_stores_entry_in_memory() -> None:
    result = log_food("Chicken burrito bowl", 600, 45, 55, 18)

    assert result["status"] == "logged"
    assert result["total_entries"] == 1
    assert get_food_log() == [
        {
            "food_name": "Chicken burrito bowl",
            "calories": 600,
            "protein_g": 45.0,
            "carbs_g": 55.0,
            "fat_g": 18.0,
        }
    ]


def test_get_food_log_returns_a_copy_of_the_log() -> None:
    log_food("Greek yogurt", 180, 20, 12, 3)
    foods = get_food_log()
    foods[0]["food_name"] = "changed outside the tool"

    assert get_food_log()[0]["food_name"] == "Greek yogurt"


def test_daily_summary_adds_logged_food_to_mock_baseline() -> None:
    assert get_daily_nutrition_summary() == {
        "calories": 1250,
        "protein_g": 82.0,
        "carbs_g": 130.0,
        "fat_g": 42.0,
        "logged_food_count": 0,
        "note": "Mock baseline plus foods logged during this process; values are approximate.",
    }

    log_food("Chicken burrito bowl", 600, 45, 55, 18)

    summary = get_daily_nutrition_summary()
    assert summary["calories"] == 1850
    assert summary["protein_g"] == 127.0
    assert summary["carbs_g"] == 185.0
    assert summary["fat_g"] == 60.0
    assert summary["logged_food_count"] == 1


@pytest.mark.parametrize(
    ("kwargs", "message"),
    [
        ({"food_name": "", "calories": 100, "protein": 10, "carbs": 10, "fat": 2}, "food_name"),
        ({"food_name": "Meal", "calories": -1, "protein": 10, "carbs": 10, "fat": 2}, "calories"),
        ({"food_name": "Meal", "calories": 100, "protein": -1, "carbs": 10, "fat": 2}, "protein"),
    ],
)
def test_log_food_rejects_invalid_values(kwargs: dict[str, object], message: str) -> None:
    with pytest.raises(ValueError, match=message):
        log_food(**kwargs)
