# ImHungry Python Tools and FastAPI Endpoints

## Status and Scope

This document defines the Strands tool contracts and HTTP REST API required by the four feature groups in `FEATURES.md` and the persistent records in `SCHEMA.md`. IMPLEMENTATION.md tracks staged implementation and verified coverage.

Restaurant menu lookup is included because restaurant menu recommendations are a core feature. Restaurant discovery remains a stretch goal and has no core endpoint or tool.

## Shared Architecture

```text
Authenticated request
        │
        ▼
     FastAPI ───────────────► Python services ──► DynamoDB / external data
        │                            ▲
        │ conversational message    │
        ▼                            │
   Strands agent ──► local tools ───┘
        │
        ├──► Amazon Bedrock
        └──► S3 Strands snapshot
```

FastAPI endpoints and Strands tools are sibling adapters over the same Python service layer. A tool does not make an HTTP request back into FastAPI, and a FastAPI route does not call a tool to perform ordinary CRUD work. This prevents duplicate validation and business logic.

The layers have these responsibilities:

- **FastAPI routes:** JWT-derived identity, HTTP validation, status codes, pagination, idempotency, and response models.
- **Strands tools:** Model-friendly names and descriptions, model-input validation, trusted invocation context, and concise structured results.
- **Python services:** BMR/TDEE calculations, nutrition arithmetic, permissions, mutation rules, aggregation, and orchestration.
- **Repositories and clients:** DynamoDB, S3, nutrition-data providers, and Bedrock access.

All request, tool, service, and response objects use shared Pydantic domain models. DynamoDB serialization into `Decimal` happens only in the repository layer.

## Authentication and User Context

The client authenticates with Cognito and sends a JWT. API Gateway and the backend validate it. The backend obtains the canonical user ID from the verified `sub` claim; no route body, query parameter, or model-generated tool input may specify `user_id`.

For conversational requests, FastAPI passes trusted context into Strands:

```python
result = await agent.invoke_async(
    request.message,
    invocation_state={
        "user_id": authenticated_user.sub,
        "conversation_id": conversation_id,
        "services": services,
    },
    idempotency_token=request.client_request_id,
)
```

Tools receive this context through Strands `ToolContext`. `@tool(context=True)` removes `tool_context` from the model-visible input schema:

```python
from strands import ToolContext, tool


@tool(context=True)
def get_user_profile(tool_context: ToolContext) -> dict:
    """Get the authenticated user's nutrition profile and preferences."""

    user_id = tool_context.invocation_state["user_id"]
    services = tool_context.invocation_state["services"]
    return services.profiles.get(user_id).model_dump(mode="json")
```

Every model-provided argument remains untrusted and is validated by Pydantic and the service layer. Tool descriptions explain exactly when a read is needed and when a write is permitted.

## Shared Domain Models

Implementation conventions: resource update tools use `entry_ref` consistently,
including recipes and patterns whose reference equals their UUID. Profile updates
also accept `expected_version`. Patches merge nested maps and then validate the
complete shared domain model. Recipe previews accept the same name/yield/ingredients
input as saved recipes. Tools never accept raw storage keys.

Planned-meal consumption links reference already logged intake on that meal's
local date. Completing a plan without linked entries records status only; the
agent logs consumption explicitly when reported. Lists use offset cursors bound
to the user and query; concurrent collection changes can shift pages. They query
all matching records initially, a deliberate modest-user-history tradeoff.

The signatures below refer to these Pydantic model families. Their fields correspond to the records already defined in `SCHEMA.md`.

| Model | Purpose |
| --- | --- |
| `ProfilePatch` | Editable profile, preference, activity-context, and presentation fields |
| `StrategyCalculationRequest` | Goal and optional overrides used to calculate BMR, TDEE, and proposed targets |
| `NutritionStrategyCreate` | An accepted, effective strategy revision |
| `FoodLookupRequest` | Search text plus optional brand, restaurant, and serving context |
| `FoodEstimateRequest` | Natural-language food description, amount, and known nutrition clues |
| `FoodIntakeCreate` / `FoodIntakePatch` | Food consumed and nutrition/provenance fields |
| `SavedFoodCreate` / `SavedFoodPatch` | Reusable food and default serving |
| `RecipeCalculationRequest` | Yield and ingredient quantities/sources |
| `RecipeCreate` / `RecipePatch` | Saved recipe fields and calculated nutrition |
| `HydrationCreate` / `HydrationPatch` | Amount, beverage, and occurrence time |
| `PlannedMealCreate` / `PlannedMealPatch` | Scheduled meal, context, menu items, alternatives, and status |
| `CheckInCreate` / `CheckInPatch` | Weight/body measurements and subjective ratings or notes |
| `BehaviorPatternCreate` / `BehaviorPatternPatch` | Confirmed recurring pattern and agreed strategies |
| `DateRange` | Validated inclusive local start and end dates |

Mutation responses return the created or updated resource, its opaque resource reference, and its current `version`. Calculation responses include inputs, results, assumptions, and warnings rather than silently filling missing data.

## Strands Python Tools

These are local Python functions registered directly with the Strands agent. They are not MCP tools and are not public HTTP endpoints.

### Tool Design Rules

- Read tools may run whenever the information is relevant.
- A clear statement such as “I ate…” authorizes the corresponding food-log write without an extra confirmation.
- Destructive operations, saving a new strategy, and confirming a behavior pattern require clear user intent.
- Tools return compact structured JSON and do not return raw DynamoDB items, PK/SK values, AWS errors, or secrets.
- Every mutation accepts or derives an idempotency key so retries do not duplicate food, hydration, check-in, or planned-meal records.
- The model performs recommendations and coaching. There is no `recommend_meal` or `coach_user` tool; tools retrieve context and persist accepted decisions.

### 1. Diet Setup Tools

```python
@tool(context=True)
def get_user_profile(tool_context: ToolContext) -> dict: ...

@tool(context=True)
def update_user_profile(
    tool_context: ToolContext,
    patch: ProfilePatch,
) -> dict: ...

@tool(context=True)
def get_nutrition_strategy(
    tool_context: ToolContext,
    on_date: str | None = None,
) -> dict: ...

@tool(context=True)
def calculate_nutrition_strategy(
    tool_context: ToolContext,
    request: StrategyCalculationRequest,
) -> dict: ...

@tool(context=True)
def save_nutrition_strategy(
    tool_context: ToolContext,
    strategy: NutritionStrategyCreate,
) -> dict: ...
```

| Tool | Type | Behavior |
| --- | --- | --- |
| `get_user_profile` | Read | Returns physical inputs, preferences, restrictions, activity context, and presentation preference. |
| `update_user_profile` | Write | Applies an explicitly requested profile change using an optimistic version check. |
| `get_nutrition_strategy` | Read | Returns the strategy effective today or on a requested historical date. |
| `calculate_nutrition_strategy` | Pure calculation | Calculates proposed BMR, TDEE, energy target, macro targets, assumptions, and warnings without saving. |
| `save_nutrition_strategy` | Append-only write | Saves an explicitly accepted strategy revision; it never overwrites historical revisions. |

The calculation service, not the language model, owns BMR/TDEE and macro arithmetic. The model may explain the result and discuss whether its assumptions are sustainable.

### 2. Food Tracking and Calculation Tools

```python
@tool(context=True)
def lookup_food_nutrition(
    tool_context: ToolContext,
    request: FoodLookupRequest,
) -> dict: ...

@tool(context=True)
def estimate_food_nutrition(
    tool_context: ToolContext,
    request: FoodEstimateRequest,
) -> dict: ...

@tool(context=True)
def log_food(
    tool_context: ToolContext,
    entry: FoodIntakeCreate,
) -> dict: ...

@tool(context=True)
def edit_food(
    tool_context: ToolContext,
    entry_ref: str,
    patch: FoodIntakePatch,
    expected_version: int,
) -> dict: ...

@tool(context=True)
def remove_food(
    tool_context: ToolContext,
    entry_ref: str,
    expected_version: int,
) -> dict: ...

@tool(context=True)
def get_food_log(
    tool_context: ToolContext,
    start_date: str,
    end_date: str | None = None,
) -> dict: ...

@tool(context=True)
def get_nutrition_summary(
    tool_context: ToolContext,
    start_date: str,
    end_date: str | None = None,
) -> dict: ...

@tool(context=True)
def calculate_recipe_nutrition(
    tool_context: ToolContext,
    request: RecipeCalculationRequest,
) -> dict: ...

@tool(context=True)
def save_recipe(
    tool_context: ToolContext,
    recipe: RecipeCreate,
) -> dict: ...

@tool(context=True)
def update_recipe(
    tool_context: ToolContext,
    recipe_id: str,
    patch: RecipePatch,
    expected_version: int,
) -> dict: ...

@tool(context=True)
def get_recipes(
    tool_context: ToolContext,
    query: str | None = None,
) -> dict: ...

@tool(context=True)
def save_food(
    tool_context: ToolContext,
    food: SavedFoodCreate,
) -> dict: ...

@tool(context=True)
def get_saved_and_frequent_foods(
    tool_context: ToolContext,
    query: str | None = None,
    lookback_days: int = 60,
) -> dict: ...

@tool(context=True)
def log_hydration(
    tool_context: ToolContext,
    entry: HydrationCreate,
) -> dict: ...

@tool(context=True)
def edit_hydration(
    tool_context: ToolContext,
    entry_ref: str,
    patch: HydrationPatch,
    expected_version: int,
) -> dict: ...

@tool(context=True)
def remove_hydration(
    tool_context: ToolContext,
    entry_ref: str,
    expected_version: int,
) -> dict: ...

@tool(context=True)
def get_hydration_summary(
    tool_context: ToolContext,
    start_date: str,
    end_date: str | None = None,
) -> dict: ...
```

`lookup_food_nutrition` prefers documented provider values and returns source metadata. `estimate_food_nutrition` is used when lookup fails or the food is homemade/underspecified; it returns ranges, confidence, and assumptions. Neither tool logs food automatically.

`edit_food` also implements replacement: it updates the selected historical entry with a new food and nutrition snapshot. `get_nutrition_summary` returns daily totals, period averages, the applicable targets, and differences from those targets. Frequently eaten foods are calculated from recent intake fingerprints so edits and removals cannot leave incorrect counters behind.

Recipe calculation is a preview; `save_recipe` persists only when requested. Recipe edits do not alter historical food logs because logs retain their own nutrition snapshots.

### 3. Meal Planning and Food-Decision Tools

```python
@tool(context=True)
def get_meal_decision_context(
    tool_context: ToolContext,
    local_date: str,
    meal_type: str | None = None,
) -> dict: ...

@tool(context=True)
def lookup_restaurant_menu(
    tool_context: ToolContext,
    restaurant_name: str,
    location: str | None = None,
    query: str | None = None,
) -> dict: ...

@tool(context=True)
def get_planned_meals(
    tool_context: ToolContext,
    start_date: str,
    end_date: str | None = None,
) -> dict: ...

@tool(context=True)
def save_planned_meal(
    tool_context: ToolContext,
    meal: PlannedMealCreate,
) -> dict: ...

@tool(context=True)
def update_planned_meal(
    tool_context: ToolContext,
    entry_ref: str,
    patch: PlannedMealPatch,
    expected_version: int,
) -> dict: ...

@tool(context=True)
def remove_planned_meal(
    tool_context: ToolContext,
    entry_ref: str,
    expected_version: int,
) -> dict: ...
```

`get_meal_decision_context` is an aggregate read optimized for the agent. It returns the profile restrictions and preferences, applicable strategy, intake and hydration so far, remaining targets, relevant saved/frequent foods and recipes, and already planned meals. This avoids forcing the model to make several predictable round trips before every recommendation.

The model uses that context to create meal suggestions, new-food ideas, substitutions, and eating-out strategies. Only a choice the user accepts becomes a `PLANNED_MEAL`. `lookup_restaurant_menu` is a provider-neutral contract and remains unimplemented until a documented nutrition-data source is selected. It searches a known restaurant's menu; it does not discover restaurants.

### 4. Adaptive Diet Coaching Tools

```python
@tool(context=True)
def log_checkin(
    tool_context: ToolContext,
    checkin: CheckInCreate,
) -> dict: ...

@tool(context=True)
def update_checkin(
    tool_context: ToolContext,
    entry_ref: str,
    patch: CheckInPatch,
    expected_version: int,
) -> dict: ...

@tool(context=True)
def get_progress_context(
    tool_context: ToolContext,
    start_date: str,
    end_date: str,
) -> dict: ...

@tool(context=True)
def get_behavior_patterns(
    tool_context: ToolContext,
    status: str = "active",
) -> dict: ...

@tool(context=True)
def save_behavior_pattern(
    tool_context: ToolContext,
    pattern: BehaviorPatternCreate,
) -> dict: ...

@tool(context=True)
def update_behavior_pattern(
    tool_context: ToolContext,
    pattern_id: str,
    patch: BehaviorPatternPatch,
    expected_version: int,
) -> dict: ...
```

`get_progress_context` returns deterministic aggregates and source records: strategy history, weight/body-measurement trend, average intake, adherence distribution, hunger/energy/recovery trends, hydration, and confirmed behavior patterns. It does not generate the coaching response; the model interprets the data.

Candidate patterns may be discussed in conversation, but `save_behavior_pattern` persists a confirmed pattern only after the user agrees. Calorie and macro adjustments use `calculate_nutrition_strategy` followed by `save_nutrition_strategy`, preserving a single target-adjustment path.

## FastAPI Conventions

- All application endpoints use the `/v1` prefix. `/health` is the only unauthenticated endpoint.
- Cognito authentication is handled outside these resource routes. FastAPI does not store passwords or expose its own login endpoint.
- Collection responses use cursor pagination where needed.
- Date ranges are inclusive local dates and are capped by service-level validation.
- Create and agent-message requests accept an `Idempotency-Key` header or equivalent `client_request_id`.
- Mutable resources return an opaque `entry_ref` and `version`. Clients do not receive raw DynamoDB PK/SK values.
- Updates and deletes require `If-Match: <version>` and return `409 Conflict` when the resource changed. Initial profile creation uses version zero. Profile tools also require an expected version.
- Validation failures return `422`, missing resources return `404`, ownership failures appear as `404`, and duplicate idempotency keys return the original completed result.
- A standard error body contains `code`, `message`, `request_id`, and optional field-level `details`.

## FastAPI Endpoint Inventory

### Health

| Method | Path | Purpose |
| --- | --- | --- |
| `GET` | `/health` | Process health check; does not invoke Bedrock or expose user data. |

### Conversations and Agent Invocation

| Method | Path | Purpose |
| --- | --- | --- |
| `POST` | `/v1/conversations` | Create conversation metadata and initialize its Strands S3 session identity. |
| `GET` | `/v1/conversations` | List the authenticated user's conversation metadata by recent activity. |
| `GET` | `/v1/conversations/{conversation_id}` | Get owned conversation metadata. |
| `PATCH` | `/v1/conversations/{conversation_id}` | Rename, archive, or unarchive a conversation. |
| `DELETE` | `/v1/conversations/{conversation_id}` | Delete owned metadata and its S3 snapshot. |
| `GET` | `/v1/conversations/{conversation_id}/messages` | Return a sanitized UI projection of restorable Strands messages. |
| `POST` | `/v1/conversations/{conversation_id}/messages` | Restore the S3 snapshot, invoke the Strands agent, save the completed snapshot, and return the assistant response. |

The message endpoint is the only general AI endpoint. Meal recommendations, substitutions, social-event planning, scale explanations, and coaching all enter through natural-language messages rather than separate copies of the agent loop.

### User Profile and Diet Setup

| Method | Path | Purpose |
| --- | --- | --- |
| `GET` | `/v1/profile` | Get the authenticated user's profile. |
| `PATCH` | `/v1/profile` | Update profile, preferences, restrictions, activity context, or presentation preference. |
| `POST` | `/v1/nutrition-strategies/calculate` | Preview BMR, TDEE, calorie targets, macro targets, assumptions, and warnings without saving. |
| `POST` | `/v1/nutrition-strategies` | Save an accepted append-only strategy revision. |
| `GET` | `/v1/nutrition-strategies/current` | Get the strategy effective now or at optional `on_date`. |
| `GET` | `/v1/nutrition-strategies` | List strategy history over an optional date range. |

### Food Log and Nutrition Summary

| Method | Path | Purpose |
| --- | --- | --- |
| `POST` | `/v1/food-log` | Log one consumed food or dish. |
| `GET` | `/v1/food-log` | List food entries for an inclusive date range. |
| `GET` | `/v1/food-log/{entry_ref}` | Get one owned food-log entry. |
| `PATCH` | `/v1/food-log/{entry_ref}` | Edit or replace one food entry. |
| `DELETE` | `/v1/food-log/{entry_ref}` | Remove one food entry. |
| `GET` | `/v1/nutrition-summary` | Return daily totals or period averages, targets, and target differences for a date range. |

`entry_ref` is a URL-safe opaque resource locator returned by the service. It lets the backend recover the date-based DynamoDB key without exposing PK/SK construction to clients.

### Food Lookup, Estimation, and Saved Foods

| Method | Path | Purpose |
| --- | --- | --- |
| `GET` | `/v1/foods/search` | Search the configured nutrition source using query, brand, restaurant, and serving filters. |
| `POST` | `/v1/foods/estimate` | Produce a structured nutrition estimate with ranges, confidence, and assumptions. |
| `GET` | `/v1/foods/frequent` | Return foods grouped from recent intake history. |
| `POST` | `/v1/saved-foods` | Save a reusable food and serving. |
| `GET` | `/v1/saved-foods` | List or text-filter the user's saved foods. |
| `GET` | `/v1/saved-foods/{food_id}` | Get one saved food. |
| `PATCH` | `/v1/saved-foods/{food_id}` | Update one saved food. |
| `DELETE` | `/v1/saved-foods/{food_id}` | Delete one saved food without altering historical logs. |

### Recipes

| Method | Path | Purpose |
| --- | --- | --- |
| `POST` | `/v1/recipes/calculate` | Preview total and per-serving nutrition from ingredients without saving. |
| `POST` | `/v1/recipes` | Save a calculated recipe. |
| `GET` | `/v1/recipes` | List or text-filter saved recipes. |
| `GET` | `/v1/recipes/{recipe_id}` | Get one recipe and its calculation inputs/results. |
| `PATCH` | `/v1/recipes/{recipe_id}` | Update and recalculate a recipe. |
| `DELETE` | `/v1/recipes/{recipe_id}` | Delete a recipe without altering historical logs. |

### Hydration

| Method | Path | Purpose |
| --- | --- | --- |
| `POST` | `/v1/hydration` | Log one hydration entry. |
| `GET` | `/v1/hydration` | List hydration entries for a date range. |
| `GET` | `/v1/hydration/{entry_ref}` | Get one owned hydration entry and its current version. |
| `PATCH` | `/v1/hydration/{entry_ref}` | Edit one hydration entry. |
| `DELETE` | `/v1/hydration/{entry_ref}` | Remove one hydration entry. |
| `GET` | `/v1/hydration-summary` | Return daily or period hydration totals against the applicable target. |

### Planned Meals, Restaurants, and Social Events

| Method | Path | Purpose |
| --- | --- | --- |
| `POST` | `/v1/planned-meals` | Save an accepted meal, restaurant choice, or social-event food plan. |
| `GET` | `/v1/planned-meals` | List planned meals for a date range. |
| `GET` | `/v1/planned-meals/{entry_ref}` | Get one planned meal. |
| `PATCH` | `/v1/planned-meals/{entry_ref}` | Replace, reschedule, complete, or skip a planned meal. |
| `DELETE` | `/v1/planned-meals/{entry_ref}` | Remove a planned meal. |
| `GET` | `/v1/restaurant-menus/search` | Search a known restaurant's documented menu nutrition; provider implementation remains pending. |

There is intentionally no `/restaurants/search` endpoint in the core API because restaurant discovery is a stretch goal.

### Check-Ins and Progress

| Method | Path | Purpose |
| --- | --- | --- |
| `POST` | `/v1/check-ins` | Record any supplied weight, body-fat estimate, hunger, cravings, food fixation, energy, recovery, or body-image note. |
| `GET` | `/v1/check-ins` | List check-ins for a date range. |
| `GET` | `/v1/check-ins/{entry_ref}` | Get one check-in. |
| `PATCH` | `/v1/check-ins/{entry_ref}` | Correct one check-in. |
| `DELETE` | `/v1/check-ins/{entry_ref}` | Delete one check-in. |
| `GET` | `/v1/progress-summary` | Return deterministic weight, intake, adherence, hunger, energy, recovery, and hydration trends for a date range. |

### Behavior Patterns and Coaching Strategies

| Method | Path | Purpose |
| --- | --- | --- |
| `POST` | `/v1/behavior-patterns` | Save a user-confirmed recurring problem and its agreed strategies. |
| `GET` | `/v1/behavior-patterns` | List patterns, optionally filtered by status or category. |
| `GET` | `/v1/behavior-patterns/{pattern_id}` | Get one confirmed or resolved pattern. |
| `PATCH` | `/v1/behavior-patterns/{pattern_id}` | Update strategies or mark a pattern confirmed, active, or resolved. |
| `DELETE` | `/v1/behavior-patterns/{pattern_id}` | Permanently remove a pattern. |

There is no separate coaching-response endpoint. The client sends the user's concern to the conversation message endpoint; the agent reads progress context and patterns through tools, then responds conversationally.

## Feature-to-Interface Coverage

| Feature group | Principal tools | Principal endpoints |
| --- | --- | --- |
| Diet setup | Profile tools and nutrition-strategy read/calculate/save tools | `/profile`, `/nutrition-strategies/*` |
| Food tracking and calculation | Food lookup/estimate/log/edit/remove, summaries, recipes, saved/frequent foods, hydration | `/food-log`, `/nutrition-summary`, `/foods/*`, `/saved-foods`, `/recipes`, `/hydration*` |
| Meal planning and decisions | Meal-decision context, restaurant-menu lookup, planned-meal persistence | Conversation messages, `/planned-meals`, `/restaurant-menus/search` |
| Adaptive diet coaching | Check-ins, progress context, behavior patterns, nutrition-strategy adjustment | Conversation messages, `/check-ins`, `/progress-summary`, `/behavior-patterns`, `/nutrition-strategies/*` |

## Explicit Non-Endpoints

- No FastAPI login or password endpoint; Cognito owns authentication.
- No public endpoint for raw S3 snapshots or raw DynamoDB items.
- No endpoint accepts `user_id`, bucket names, object keys, PK values, or SK values.
- No HTTP endpoint per Strands tool; tools are in-process adapters.
- No separate endpoint for generic meal recommendations, substitutions, or coaching; these are agent responses.
- No restaurant-discovery endpoint in the core scope.
- No workout-programming, body-image upload, image estimation, database administration, or MCP endpoint.

## Implementation Order

The contracts do not imply that all routes and tools should be implemented at once. A safe incremental order is:

1. Shared Pydantic models and service interfaces.
2. Cognito-derived request context and DynamoDB repositories.
3. Profile, strategy, food-log, summary, and conversation endpoints/tools.
4. Recipe, saved-food, and hydration interfaces.
5. Planned meals and restaurant-menu provider integration.
6. Check-ins, progress aggregation, and behavior-pattern coaching.

Each stage should add repository tests, service tests, tool tests, and FastAPI endpoint tests before the next stage begins.

## References

- [Strands Python tools](https://strandsagents.com/latest/documentation/docs/user-guide/concepts/tools/python-tools/)
- [FastAPI documentation](https://fastapi.tiangolo.com/)
- [Amazon Bedrock security best practices](https://docs.aws.amazon.com/bedrock/latest/userguide/security.html)
