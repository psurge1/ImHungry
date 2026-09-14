"""Model-facing sibling adapters; trusted invocation state supplies identity."""

from functools import wraps
import inspect

from pydantic import BaseModel, ValidationError
from strands import ToolContext, tool

from .errors import AppError
from .models import (Intake, Strategy, StrategyCalculationRequest, Recipe, SavedFood,
                     Hydration, PlannedMeal, CheckIn, BehaviorPattern, FoodLookupRequest, FoodEstimateRequest)


def safe_tool(function):
    signature = inspect.signature(function)
    @wraps(function)
    def safe(*args, **kwargs):
        try:
            bound = signature.bind(*args, **kwargs)
            for name, value in bound.arguments.items():
                annotation = signature.parameters[name].annotation
                if inspect.isclass(annotation) and issubclass(annotation, BaseModel):
                    # Strands 1.55.1 validates and model_dump()s nested inputs.
                    bound.arguments[name] = annotation.model_validate(value)
            return function(*bound.args, **bound.kwargs)
        except AppError as error:
            return {"error": {"code": error.code, "message": error.message}}
        except (ValidationError, ValueError, TypeError):
            return {"error": {"code": "validation", "message": "Invalid tool input; check required fields and values"}}
        except Exception:
            return {"error": {"code": "service_unavailable", "message": "Unable to complete this operation"}}
    return tool(context=True)(safe)


def context(tool_context):
    state = tool_context.invocation_state
    if not state.get("user_id") or "services" not in state:
        raise AppError("identity", "Trusted invocation context is required", 401)
    return state["services"], state["user_id"]


def mutation_key(tool_context):
    request_id = tool_context.invocation_state.get("request_id")
    tool_id = tool_context.tool_use.get("toolUseId")
    if not request_id or not tool_id:
        raise AppError("identity", "Trusted request identity is required", 401)
    from .services import digest
    return digest([request_id, tool_id])


@safe_tool
def get_user_profile(tool_context: ToolContext) -> dict:
    """Read the user's saved physical inputs, activity and dietary restrictions."""
    services, user = context(tool_context)
    return services.get(user, "profile")


@safe_tool
def update_user_profile(tool_context: ToolContext, patch: dict, expected_version: int) -> dict:
    """Apply an explicitly requested profile change using the last read version (zero for setup)."""
    services, user = context(tool_context)
    return services.update(user, "profile", "profile", patch, expected_version, mutation_key(tool_context))


@safe_tool
def get_nutrition_strategy(tool_context: ToolContext, on_date: str | None = None) -> dict:
    """Read the strategy effective now or on a historical local YYYY-MM-DD date."""
    services, user = context(tool_context)
    return {"strategy": services.current_strategy(user, on_date)}


@safe_tool
def calculate_nutrition_strategy(tool_context: ToolContext, request: StrategyCalculationRequest) -> dict:
    """Preview BMR, TDEE and targets. This never saves a strategy."""
    services, user = context(tool_context)
    return services.calculate_strategy(user, request.data())


@safe_tool
def save_nutrition_strategy(tool_context: ToolContext, strategy: Strategy) -> dict:
    """Save an explicitly accepted strategy revision; never overwrite target history."""
    services, user = context(tool_context)
    return services.create(user, "nutrition-strategies", strategy.data(), mutation_key(tool_context))


@safe_tool
def log_food(tool_context: ToolContext, entry: Intake) -> dict:
    """Log reported consumption with all core nutrition values. 'I ate' authorizes logging; never invent missing values."""
    services, user = context(tool_context)
    return services.create(user, "food-log", entry.data(), mutation_key(tool_context))


@safe_tool
def edit_food(tool_context: ToolContext, entry_ref: str, patch: dict, expected_version: int) -> dict:
    """Edit or replace a selected logged food only on clear user intent; use its current version."""
    services, user = context(tool_context)
    return services.update(user, "food-log", entry_ref, patch, expected_version, mutation_key(tool_context))


@safe_tool
def remove_food(tool_context: ToolContext, entry_ref: str, expected_version: int) -> dict:
    """Remove a selected food only when the user clearly requests deletion."""
    services, user = context(tool_context)
    return services.delete(user, "food-log", entry_ref, expected_version, mutation_key(tool_context))


@safe_tool
def get_food_log(tool_context: ToolContext, start_date: str, end_date: str | None = None) -> dict:
    """Read recorded foods over an inclusive local date range of at most 366 days."""
    services, user = context(tool_context)
    return {"items": services.records(user, "food-log", start_date, end_date)}


@safe_tool
def get_nutrition_summary(tool_context: ToolContext, start_date: str, end_date: str | None = None) -> dict:
    """Read logged totals, averages and remaining dated targets; missing logs do not imply fasting."""
    services, user = context(tool_context)
    return services.summary(user, start_date, end_date)


TOOLS = [get_user_profile, update_user_profile, get_nutrition_strategy,
         calculate_nutrition_strategy, save_nutrition_strategy, log_food,
         edit_food, remove_food, get_food_log, get_nutrition_summary]


@safe_tool
def calculate_recipe_nutrition(tool_context: ToolContext, request: Recipe) -> dict:
    """Preview total and per-serving nutrition from ingredient quantities. Does not save."""
    services, _ = context(tool_context)
    return services.calculate_recipe(request.data())


@safe_tool
def save_recipe(tool_context: ToolContext, recipe: Recipe) -> dict:
    """Save a recipe when the user requests it; calculate from its ingredient nutrition."""
    services, user = context(tool_context)
    return services.create(user, "recipes", recipe.data(), mutation_key(tool_context))


@safe_tool
def save_food(tool_context: ToolContext, food: SavedFood) -> dict:
    """Save a reusable food and serving on the user's request."""
    services, user = context(tool_context)
    return services.create(user, "saved-foods", food.data(), mutation_key(tool_context))


@safe_tool
def log_hydration(tool_context: ToolContext, entry: Hydration) -> dict:
    """Log a drink the user reports consuming; do not infer unreported hydration."""
    services, user = context(tool_context)
    return services.create(user, "hydration", entry.data(), mutation_key(tool_context))


@safe_tool
def save_planned_meal(tool_context: ToolContext, meal: PlannedMeal) -> dict:
    """Save a meal, restaurant choice or event plan only after the user accepts it."""
    services, user = context(tool_context)
    return services.create(user, "planned-meals", meal.data(), mutation_key(tool_context))


@safe_tool
def log_checkin(tool_context: ToolContext, checkin: CheckIn) -> dict:
    """Save user-reported measurements or feelings; do not infer measurements or diagnoses."""
    services, user = context(tool_context)
    return services.create(user, "check-ins", checkin.data(), mutation_key(tool_context))


@safe_tool
def save_behavior_pattern(tool_context: ToolContext, pattern: BehaviorPattern) -> dict:
    """Save a recurring problem and agreed strategies only after explicit user confirmation."""
    services, user = context(tool_context)
    return services.create(user, "behavior-patterns", pattern.data(), mutation_key(tool_context))


@safe_tool
def get_recipes(tool_context: ToolContext, query: str | None = None, cursor: str | None = None) -> dict:
    """Read saved recipes, optionally matching a food or recipe name."""
    services, user = context(tool_context)
    return services.list(user, "recipes", query=query, cursor=cursor)


@safe_tool
def get_saved_and_frequent_foods(tool_context: ToolContext, query: str | None = None, lookback_days: int = 60, cursor: str | None = None) -> dict:
    """Read reusable foods and frequency derived from recent actual intake."""
    services, user = context(tool_context)
    page = services.list(user, "saved-foods", query=query, cursor=cursor)
    return {"saved_foods": page["items"], "next_cursor": page["next_cursor"], "frequent_foods": services.frequent_foods(user, query, lookback_days)}


@safe_tool
def get_hydration_summary(tool_context: ToolContext, start_date: str, end_date: str | None = None) -> dict:
    """Read recorded hydration totals and applicable dated hydration targets."""
    services, user = context(tool_context)
    return services.hydration_summary(user, start_date, end_date)


@safe_tool
def get_planned_meals(tool_context: ToolContext, start_date: str, end_date: str | None = None) -> dict:
    """Read accepted meals and social-event plans in an inclusive local date range."""
    services, user = context(tool_context)
    return {"items": services.records(user, "planned-meals", start_date, end_date)}


@safe_tool
def get_meal_decision_context(tool_context: ToolContext, local_date: str, meal_type: str | None = None) -> dict:
    """Read preferences, allergies, dated targets, intake, hydration, saved foods and plans before suggesting meals."""
    services, user = context(tool_context)
    return services.meal_context(user, local_date, meal_type)


@safe_tool
def get_progress_context(tool_context: ToolContext, start_date: str, end_date: str) -> dict:
    """Read weight, intake, hunger, energy and recovery trends for coaching; unlogged intake is unknown."""
    services, user = context(tool_context)
    return services.progress(user, start_date, end_date)


@safe_tool
def get_behavior_patterns(tool_context: ToolContext, status: str = "active") -> dict:
    """Read confirmed recurring problems and strategies; active includes newly confirmed patterns."""
    services, user = context(tool_context)
    items = services.records(user, "behavior-patterns")
    return {"items": [p for p in items if p["status"] == status or (status == "active" and p["status"] == "confirmed")]}


@safe_tool
def lookup_food_nutrition(tool_context: ToolContext, request: FoodLookupRequest) -> dict:
    """Search configured documented nutrition values without logging food. May report provider unavailable."""
    services, user = context(tool_context)
    return services.lookup_food(user, request.data())


@safe_tool
def estimate_food_nutrition(tool_context: ToolContext, request: FoodEstimateRequest) -> dict:
    """Estimate nutrition with ranges and assumptions when documented lookup is unavailable. Does not log food."""
    services, user = context(tool_context)
    return services.estimate_food(user, request.data())


@safe_tool
def lookup_restaurant_menu(tool_context: ToolContext, restaurant_name: str, location: str | None = None, query: str | None = None) -> dict:
    """Look up a known restaurant's documented menu; this does not discover restaurants."""
    services, user = context(tool_context)
    return services.restaurant_menu(user, restaurant_name, location, query)


def update_adapter(name, kind):
    def update(tool_context: ToolContext, entry_ref: str, patch: dict, expected_version: int) -> dict:
        services, user = context(tool_context)
        return services.update(user, kind, entry_ref, patch, expected_version, mutation_key(tool_context))
    update.__name__ = name
    update.__doc__ = f"Update a selected {kind} record only on clear user intent. Use its entry_ref and current version."
    return safe_tool(update)


def delete_adapter(name, kind):
    def delete(tool_context: ToolContext, entry_ref: str, expected_version: int) -> dict:
        services, user = context(tool_context)
        return services.delete(user, kind, entry_ref, expected_version, mutation_key(tool_context))
    delete.__name__ = name
    delete.__doc__ = f"Delete a selected {kind} record only when the user explicitly requests removal."
    return safe_tool(delete)


TOOLS += [calculate_recipe_nutrition, save_recipe, save_food, log_hydration,
          save_planned_meal, log_checkin, save_behavior_pattern, get_recipes,
          get_saved_and_frequent_foods, get_hydration_summary, get_planned_meals,
          get_meal_decision_context, get_progress_context, get_behavior_patterns,
          lookup_food_nutrition, estimate_food_nutrition, lookup_restaurant_menu]
TOOLS += [update_adapter(name, kind) for name, kind in [
    ("update_recipe", "recipes"), ("edit_hydration", "hydration"),
    ("update_planned_meal", "planned-meals"), ("update_checkin", "check-ins"),
    ("update_behavior_pattern", "behavior-patterns")]]
TOOLS += [delete_adapter(name, kind) for name, kind in [
    ("remove_hydration", "hydration"), ("remove_planned_meal", "planned-meals")]]
