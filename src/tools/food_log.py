"""In-memory food logging tools."""

from __future__ import annotations

from numbers import Real
from typing import Any

from strands import tool

_FOOD_LOG: list[dict[str, Any]] = []


def _validate_non_negative_number(value: Real, field_name: str) -> float:
    """Validate and normalize a numeric nutrition value."""

    if isinstance(value, bool) or not isinstance(value, Real):
        raise ValueError(f"{field_name} must be a number")
    if value < 0:
        raise ValueError(f"{field_name} cannot be negative")
    return float(value)


@tool
def log_food(
    food_name: str,
    calories: int,
    protein: float,
    carbs: float,
    fat: float,
) -> dict[str, Any]:
    """Log one food entry in memory for the lifetime of this process.

    Calories are in kcal and the macronutrients are in grams. Values are
    intentionally supplied by the caller in this milestone; the tool does not
    estimate nutrition from a food name.
    """

    if not isinstance(food_name, str) or not food_name.strip():
        raise ValueError("food_name must be a non-empty string")
    if isinstance(calories, bool) or not isinstance(calories, int):
        raise ValueError("calories must be an integer")
    if calories < 0:
        raise ValueError("calories cannot be negative")

    entry = {
        "food_name": food_name.strip(),
        "calories": calories,
        "protein_g": _validate_non_negative_number(protein, "protein"),
        "carbs_g": _validate_non_negative_number(carbs, "carbs"),
        "fat_g": _validate_non_negative_number(fat, "fat"),
    }
    _FOOD_LOG.append(entry)

    return {
        "status": "logged",
        "entry": entry.copy(),
        "total_entries": len(_FOOD_LOG),
    }


@tool
def get_food_log() -> list[dict[str, Any]]:
    """Return all foods logged during the current process lifetime."""

    return [entry.copy() for entry in _FOOD_LOG]


def _clear_food_log() -> None:
    """Clear the process-local log for test isolation."""

    _FOOD_LOG.clear()
