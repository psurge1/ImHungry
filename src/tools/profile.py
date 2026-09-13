"""Example user profile tool."""

from typing import Any

from strands import tool


@tool
def get_user_profile() -> dict[str, Any]:
    """Return the example user's goals, body metrics, activity, and preferences."""

    return {
        "goal": "lose weight gradually while maintaining energy",
        "height_cm": 175,
        "weight_kg": 82,
        "activity_level": "moderately active",
        "dietary_preferences": ["omnivore", "high-protein meals"],
        "dietary_restrictions": [],
    }
