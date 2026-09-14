"""Model-facing sibling adapters; trusted invocation state supplies identity."""

from functools import wraps

from pydantic import ValidationError
from strands import ToolContext, tool

from .errors import AppError
from .models import Intake, Strategy, StrategyCalculationRequest


def safe_tool(function):
    @wraps(function)
    def safe(*args, **kwargs):
        try:
            return function(*args, **kwargs)
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
