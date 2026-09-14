"""Validated domain inputs. Unknown values stay absent; storage owns keys."""

from datetime import date, datetime, timezone
from typing import Annotated, Literal
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from pydantic import BaseModel, ConfigDict, Field, AwareDatetime, field_validator, model_validator

Number = Annotated[float, Field(ge=0, le=1e9, allow_inf_nan=False, strict=True)]
Positive = Annotated[float, Field(gt=0, le=1e9, allow_inf_nan=False, strict=True)]
Text = Annotated[str, Field(min_length=1, max_length=2000)]
Rating = Annotated[int, Field(ge=1, le=10, strict=True)]
Meal = Literal["breakfast", "lunch", "dinner", "snack", "other"]


class Model(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True, allow_inf_nan=False, populate_by_name=True)

    def data(self):
        return self.model_dump(mode="json", by_alias=True, exclude_none=True)


class Nutrition(Model):
    energy_kcal: Number
    protein_g: Number
    carbs_g: Number
    fat_g: Number
    fiber_g: Number | None = None
    sodium_mg: Number | None = None


class Targets(Nutrition):
    hydration_ml: Positive | None = None


class Source(Model):
    type: Literal["user_provided", "package_label", "external_database", "restaurant_official", "recipe", "saved_food", "model_estimate"]
    provider: Text | None = None
    external_id: Text | None = None
    source_url: Text | None = None
    recipe_id: Text | None = None
    saved_food_id: Text | None = None


class Range(Model):
    minimum: Number
    maximum: Number

    @model_validator(mode="after")
    def ordered(self):
        if self.minimum > self.maximum:
            raise ValueError("minimum must not exceed maximum")
        return self


class Estimate(Model):
    is_estimate: Literal[True] = True
    confidence: Literal["low", "medium", "high"]
    ranges: dict[str, Range]
    assumptions: list[Text] = Field(min_length=1, max_length=30)

    @field_validator("ranges")
    @classmethod
    def valid_ranges(cls, value):
        if not value or not set(value) <= set(Nutrition.model_fields):
            raise ValueError("Provide ranges for known nutrition fields")
        return value


class Activity(Model):
    level: Literal["sedentary", "lightly_active", "moderately_active", "very_active", "extra_active"]
    resistance_training_sessions_per_week: Annotated[int, Field(ge=0, le=14)] | None = None
    notes: Text | None = None


class Profile(Model):
    timezone: str = "UTC"
    unit_system: Literal["metric", "imperial"] = "metric"
    height_cm: Annotated[float, Field(gt=50, le=250)] | None = None
    date_of_birth: date | None = None
    sex_for_bmr_equation: Literal["male", "female"] | None = None
    dietary_preferences: list[Text] = Field(default_factory=list, max_length=50)
    dietary_restrictions: list[Text] = Field(default_factory=list, max_length=50)
    allergies: list[Text] = Field(default_factory=list, max_length=50)
    disliked_foods: list[Text] = Field(default_factory=list, max_length=50)
    activity_context: Activity | None = None
    presentation_mode: Literal["explicit", "low_obsession"] = "explicit"

    @field_validator("timezone")
    @classmethod
    def valid_zone(cls, value):
        try:
            ZoneInfo(value)
        except (ZoneInfoNotFoundError, ValueError):
            raise ValueError("Unknown IANA timezone") from None
        return value

    @field_validator("date_of_birth")
    @classmethod
    def valid_birth(cls, value):
        if value and value > datetime.now(timezone.utc).date():
            raise ValueError("Birth date cannot be in the future")
        return value


class Goal(Model):
    type: Literal["lose_weight", "maintain_weight"]
    baseline_weight_kg: Annotated[float, Field(gt=20, le=500)]
    goal_weight_kg: Annotated[float, Field(gt=20, le=500)]
    desired_rate_kg_per_week: Annotated[float, Field(ge=0, le=1)] = 0

    @model_validator(mode="after")
    def consistent(self):
        if self.type == "maintain_weight" and self.desired_rate_kg_per_week != 0:
            raise ValueError("Maintenance requires zero loss rate")
        if self.type == "lose_weight" and self.goal_weight_kg >= self.baseline_weight_kg:
            raise ValueError("Loss goal must be below starting weight")
        return self


class StrategyCalculationRequest(Model):
    goal: Goal
    protein_g_per_kg: Annotated[float, Field(ge=0.8, le=2.5)] = 1.6
    fat_fraction: Annotated[float, Field(ge=0.2, le=0.4)] = 0.3
    hydration_ml: Positive | None = None


class Calculation(Model):
    method: Literal["mifflin_st_jeor", "user_provided"]
    method_version: Literal[1] = 1
    inputs: dict[str, str | float]
    results: dict[str, Number]
    assumptions: list[Text] = Field(default_factory=list, max_length=30)


class Strategy(Model):
    effective_from: AwareDatetime
    goal: Goal
    targets: Targets
    calculation: Calculation
    change_reason: Text
    notes: Text | None = None


class Food(Model):
    display_name: Text
    quantity: Positive
    unit: Text
    serving_description: Text


class Intake(Model):
    consumed_at: AwareDatetime
    meal_type: Meal = "other"
    meal_group_id: Text | None = None
    food: Food
    nutrition: Nutrition
    source: Source
    estimate: Estimate | None = None
    notes: Text | None = None

    @model_validator(mode="after")
    def estimated_source(self):
        if self.source.type == "model_estimate" and self.estimate is None:
            raise ValueError("Model estimates require uncertainty and assumptions")
        if self.estimate:
            for name, bounds in self.estimate.ranges.items():
                number = getattr(self.nutrition, name)
                if number is not None and not bounds.minimum <= number <= bounds.maximum:
                    raise ValueError("Nutrition must fall within its estimate range")
        return self


class Serving(Model):
    quantity: Positive
    unit: Text


class SavedFood(Model):
    name: Text
    aliases: list[Text] = Field(default_factory=list, max_length=30)
    default_serving: Serving
    nutrition_per_serving: Nutrition
    source: Source


class Ingredient(Model):
    name: Text
    quantity: Positive
    unit: Text
    nutrition_for_quantity: Nutrition
    source: Source


class Yield(Model):
    servings: Positive
    serving_description: Text = "one serving"


class Recipe(Model):
    name: Text
    recipe_yield: Yield = Field(alias="yield")
    ingredients: list[Ingredient] = Field(min_length=1, max_length=100)


class Hydration(Model):
    consumed_at: AwareDatetime
    amount_ml: Annotated[float, Field(gt=0, le=10000)]
    beverage_name: Text = "water"
    notes: Text | None = None


class MealContext(Model):
    type: Literal["ordinary", "restaurant", "eating_out", "social_event"] = "ordinary"
    venue_name: Text | None = None
    event_description: Text | None = None


class MealItem(Model):
    name: Text
    serving_description: Text
    recipe_id: Text | None = None
    saved_food_id: Text | None = None
    nutrition: Nutrition | None = None
    source: Source | None = None


class Alternative(Model):
    name: Text
    reason: Text


class PlannedMeal(Model):
    scheduled_at: AwareDatetime
    meal_slot: Meal
    status: Literal["planned", "completed", "skipped"] = "planned"
    context: MealContext = Field(default_factory=MealContext)
    items: list[MealItem] = Field(min_length=1, max_length=50)
    alternatives: list[Alternative] = Field(default_factory=list, max_length=50)
    recommendation_summary: Text | None = None
    strategy_effective_from: AwareDatetime | None = None
    source_conversation_id: Text | None = None
    completed_intake_entry_ids: list[Text] = Field(default_factory=list, max_length=50)


class Measurements(Model):
    weight_kg: Annotated[float, Field(gt=20, le=500)] | None = None
    body_fat_percent: Annotated[float, Field(gt=0, lt=100)] | None = None
    body_fat_source: Literal["user_estimate", "device", "clinical"] | None = None
    waist_cm: Positive | None = None

    @model_validator(mode="after")
    def source_required(self):
        if self.body_fat_percent is not None and not self.body_fat_source:
            raise ValueError("Body-fat estimates require a source")
        return self


class Craving(Model):
    food: Text
    intensity: Rating


class Subjective(Model):
    hunger: Rating | None = None
    energy: Rating | None = None
    recovery: Rating | None = None
    food_fixation: Rating | None = None
    cravings: list[Craving] = Field(default_factory=list, max_length=50)
    body_image_note: Text | None = None


class CheckIn(Model):
    recorded_at: AwareDatetime
    measurements: Measurements = Field(default_factory=Measurements)
    subjective: Subjective = Field(default_factory=Subjective)
    context_tags: list[Text] = Field(default_factory=list, max_length=50)
    notes: Text | None = None

    @model_validator(mode="after")
    def nonempty(self):
        if not (self.measurements.data() or any(self.subjective.data().values()) or self.notes):
            raise ValueError("Provide at least one measurement, rating or note")
        return self


class BehaviorStrategy(Model):
    type: Text
    description: Text


class BehaviorPattern(Model):
    category: Text
    description: Text
    status: Literal["confirmed", "active", "resolved"] = "confirmed"
    user_confirmed: Literal[True]
    triggers: list[Text] = Field(default_factory=list, max_length=50)
    foods: list[Text] = Field(default_factory=list, max_length=50)
    strategies: list[BehaviorStrategy] = Field(default_factory=list, max_length=50)
    first_observed_at: AwareDatetime | None = None
    last_observed_at: AwareDatetime | None = None
    evidence_window_days: Annotated[int, Field(ge=1, le=366)] | None = None
    source_conversation_id: Text | None = None


class Conversation(Model):
    title: Annotated[str, Field(min_length=1, max_length=200)] = "Nutrition conversation"
    status: Literal["active", "archived"] = "active"


class DateRange(Model):
    start_date: date
    end_date: date | None = None

    @model_validator(mode="after")
    def bounded(self):
        self.end_date = self.end_date or self.start_date
        if not 0 <= (self.end_date - self.start_date).days <= 365:
            raise ValueError("Date range must contain 1 to 366 days")
        return self


class FoodLookupRequest(Model):
    query: Annotated[str, Field(min_length=1, max_length=200)]
    brand: Text | None = None
    restaurant: Text | None = None
    serving: Text | None = None


class FoodEstimateRequest(Model):
    description: Text
    quantity: Positive
    unit: Text
    known_nutrition: dict[str, Number] = Field(default_factory=dict)

    @field_validator("known_nutrition")
    @classmethod
    def known_fields(cls, value):
        if not set(value) <= set(Nutrition.model_fields):
            raise ValueError("Unknown nutrition field")
        return value


class NutritionResult(Model):
    food: Food
    nutrition: Nutrition
    source: Source
    estimate: Estimate | None = None

    @model_validator(mode="after")
    def valid_estimate(self):
        Intake(consumed_at=datetime.now(timezone.utc), food=self.food, nutrition=self.nutrition,
               source=self.source, estimate=self.estimate)
        return self


class EstimatedNutrition(NutritionResult):
    estimate: Estimate


RECORDS = {
    "profile": ("PROFILE", Profile, "user_profile", None),
    "nutrition-strategies": ("NUTRITION_STRATEGY", Strategy, "nutrition_strategy", None),
    "food-log": ("INTAKE", Intake, "food_intake", "consumed_at"),
    "saved-foods": ("SAVED_FOOD", SavedFood, "saved_food", None),
    "recipes": ("RECIPE", Recipe, "recipe", None),
    "hydration": ("HYDRATION", Hydration, "hydration", "consumed_at"),
    "planned-meals": ("PLANNED_MEAL", PlannedMeal, "planned_meal", "scheduled_at"),
    "check-ins": ("CHECKIN", CheckIn, "checkin", "recorded_at"),
    "behavior-patterns": ("BEHAVIOR_PATTERN", BehaviorPattern, "behavior_pattern", None),
    "conversations": ("CONVERSATION", Conversation, "conversation", None),
}
