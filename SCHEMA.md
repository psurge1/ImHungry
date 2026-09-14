# ImHungry Persistence Schema

## Status and Scope

This document defines the persistent data formats for the four product feature groups in `FEATURES.md`. Implementation progress and verification are recorded in IMPLEMENTATION.md.

The S3 schema below restates the previously approved decision without changing it. The DynamoDB schema is derived from the complete feature list and replaces the preliminary DynamoDB proposal in `ARCHITECTURE.md` when the two disagree.

## Persistence Boundaries

- **Amazon S3** stores the complete restorable Strands conversation snapshot: messages, agent responses, tool calls, tool results, and agent state.
- **Amazon DynamoDB** stores canonical product data that must be queryable, editable, or available across conversations.
- **Amazon Bedrock** processes context but is not a data store.
- Generated advice is retained in the S3 conversation. If the user accepts, schedules, saves, or confirms something, it is also represented as structured DynamoDB data.
- Derived values such as daily totals, averages, trends, and current remaining targets are calculated from canonical DynamoDB records. They do not need to be duplicated to be persistent features.

## S3 Conversation Snapshot Schema

This section is the frozen S3 decision. ImHungry uses the native Strands `SnapshotSessionManager` format rather than defining a custom transcript format.

With an `S3Storage` prefix of `imhungry/<environment>`, a server-generated conversation ID as the Strands session ID, and the stable agent ID `dietitian`, the latest snapshot is stored at:

```text
imhungry/<environment>/session/<conversation-id>/scopes/agent/dietitian/snapshots/snapshot_latest.json
```

The initial design writes only `snapshot_latest.json` after each completed agent invocation. It does not write an immutable snapshot for every turn. The latest object contains the agent's current restorable conversation, including tool calls and results; it is session state, not a permanent audit log of every pre-summarization message.

The object shape is owned and versioned by Strands:

```json
{
  "scope": "agent",
  "schema_version": "1.0",
  "created_at": "2026-09-14T18:30:00.000000+00:00",
  "data": {
    "messages": [
      {
        "role": "user",
        "content": [{"text": "What should I eat for dinner?"}],
        "tracking_id": "<message-uuid>"
      },
      {
        "role": "assistant",
        "content": [{
          "toolUse": {
            "toolUseId": "<tool-use-id>",
            "name": "get_daily_nutrition_summary",
            "input": {}
          }
        }],
        "tracking_id": "<message-uuid>"
      },
      {
        "role": "user",
        "content": [{
          "toolResult": {
            "toolUseId": "<tool-use-id>",
            "status": "success",
            "content": [{"json": {"calories": 1250, "protein": 92}}]
          }
        }],
        "tracking_id": "<message-uuid>"
      }
    ],
    "state": {},
    "conversation_manager_state": {},
    "interrupt_state": {},
    "model_state": {},
    "system_prompt": [{"text": "<dietitian-system-prompt>"}]
  },
  "app_data": {}
}
```

`messages` uses Bedrock-style content blocks, so normal text, model-requested `toolUse` blocks, and matching `toolResult` blocks are preserved in order. `state` contains application-visible Strands agent state; the remaining state fields let Strands resume context management, interrupted work, model-specific state, and the system prompt. ImHungry treats this object as opaque framework state and does not query or partially update its JSON.

Conversation ownership does not come from the S3 key. Before opening a snapshot, the backend gets the `CONVERSATION#<conversation-id>` item from the authenticated user's DynamoDB partition; only then does it construct the fixed S3 key. The client and model never provide a bucket name, object key, Cognito user ID, or storage prefix.

## DynamoDB Table

ImHungry uses one table per environment, named conceptually `imhungry-<environment>`.

| Key | Type | Meaning |
| --- | --- | --- |
| `PK` | String partition key | `USER#<cognito-sub>` for every user-owned item |
| `SK` | String sort key | Identifies the record type and, where useful, its date and time |

Keeping a user's records in one logical partition supports the dominant access pattern: retrieve a known category of data for one authenticated user. Composite sort-key prefixes let the backend select only profiles, strategies, intake entries, recipes, check-ins, or other relevant records without scanning the table.

### Data Conventions

- The verified Cognito `sub` claim is the user ID. It is never accepted from the client or model.
- Timestamps use ISO 8601 UTC, such as `2026-09-14T18:42:00Z`.
- Date-based records also store `local_date` as `YYYY-MM-DD` in the user's saved time zone.
- Quantities use canonical metric units internally: kilograms, centimeters, grams, milligrams, milliliters, and kilocalories. Presentation code may convert them.
- DynamoDB numbers are represented with Python `Decimal`, not binary `float`, in the persistence layer.
- Optional unknown values are omitted rather than stored as invented zeros.
- IDs are server-generated and opaque. They exist only for records that must be edited, deleted, referenced, or disambiguated.
- Python Pydantic models define and validate each record shape because DynamoDB itself does not enforce non-key attributes.

### Common Attributes

Every item contains:

```json
{
  "PK": "USER#<cognito-sub>",
  "SK": "<record-specific-sort-key>",
  "record_type": "<record-type>",
  "schema_version": 1,
  "created_at": "<UTC timestamp>"
}
```

Mutable items also contain `updated_at` and an integer `version`. Updates use the previously read `version` in a DynamoDB condition expression so simultaneous edits do not silently overwrite each other. `record_type` selects the correct Pydantic model, while `schema_version` gives future migrations an explicit boundary; neither is merely display metadata.

## DynamoDB Record Schemas

### 1. User Profile

```text
PK = USER#<user-id>
SK = PROFILE
```

```json
{
  "record_type": "user_profile",
  "timezone": "America/Chicago",
  "unit_system": "imperial",
  "height_cm": 178,
  "date_of_birth": "1995-04-12",
  "sex_for_bmr_equation": "male",
  "dietary_preferences": ["high_protein"],
  "dietary_restrictions": [],
  "allergies": [],
  "disliked_foods": [],
  "activity_context": {
    "level": "moderately_active",
    "resistance_training_sessions_per_week": 3,
    "notes": null
  },
  "presentation_mode": "explicit",
  "updated_at": "<UTC timestamp>",
  "version": 1
}
```

`date_of_birth`, `sex_for_bmr_equation`, and `height_cm` provide inputs required by common BMR equations. They may be omitted if the user does not provide them, in which case the calculation service must report that its estimate is incomplete. Resistance-training frequency is nutrition context for muscle preservation, not workout programming.

Starting weight and goal weight do not live in the profile because they belong to a dated nutrition strategy. This avoids silently rewriting the historical basis for earlier targets.

### 2. Nutrition Strategy Revision

```text
PK = USER#<user-id>
SK = NUTRITION_STRATEGY#<effective-from-UTC>
```

```json
{
  "record_type": "nutrition_strategy",
  "effective_from": "2026-09-14T00:00:00Z",
  "goal": {
    "type": "lose_weight",
    "baseline_weight_kg": 82.5,
    "goal_weight_kg": 74,
    "desired_rate_kg_per_week": 0.4
  },
  "targets": {
    "energy_kcal": 2331,
    "protein_g": 132,
    "carbs_g": 275.86,
    "fat_g": 77.69,
    "hydration_ml": 2500
  },
  "calculation": {
    "method": "mifflin_st_jeor",
    "method_version": 1,
    "inputs": {
      "age_years": 31,
      "sex_for_equation": "male",
      "height_cm": 178,
      "weight_kg": 82.5,
      "activity_level": "moderately_active",
      "activity_multiplier": 1.55,
      "protein_g_per_kg": 1.6,
      "fat_fraction": 0.3
    },
    "results": {
      "bmr_kcal": 1787.5,
      "tdee_kcal": 2770.62
    },
    "assumptions": ["Activity multiplier is self-reported", "7700 kcal/kg is an approximate planning conversion"]
  },
  "change_reason": "initial_setup",
  "notes": null
}
```

There is deliberately no `plan_id`. A user has an append-only timeline of strategy revisions. The current strategy is the latest item with `effective_from` at or before the requested time, and the strategy applicable to a historical date can be retrieved the same way. Adjusting targets appends another revision instead of mutating history.

The initial revision preserves starting weight, goal weight, BMR/TDEE inputs, outputs, and initial targets. Later revisions preserve the information used for each adjustment. BMR and TDEE remain calculated values, but recording the calculation snapshot makes past decisions explainable and reproducible.

### 3. Food Intake Entry

```text
PK = USER#<user-id>
SK = INTAKE#<local-date>#<consumed-at-UTC>#<entry-id>
```

```json
{
  "record_type": "food_intake",
  "entry_id": "<uuid>",
  "local_date": "2026-09-14",
  "consumed_at": "2026-09-14T18:42:00Z",
  "meal_type": "lunch",
  "meal_group_id": null,
  "food": {
    "display_name": "Chicken burrito bowl",
    "normalized_name": "chicken burrito bowl",
    "food_fingerprint": "<deterministic-food-fingerprint>",
    "quantity": 1,
    "unit": "bowl",
    "serving_description": "1 bowl"
  },
  "nutrition": {
    "energy_kcal": 600,
    "protein_g": 45,
    "carbs_g": 68,
    "fat_g": 17,
    "fiber_g": 10,
    "sodium_mg": 1050
  },
  "source": {
    "type": "user_provided",
    "provider": null,
    "external_id": null,
    "source_url": null,
    "recipe_id": null,
    "saved_food_id": null
  },
  "estimate": {
    "is_estimate": true,
    "confidence": "medium",
    "ranges": {
      "energy_kcal": {"minimum": 500, "maximum": 700}
    },
    "assumptions": ["Standard restaurant-sized portion"]
  },
  "notes": null,
  "updated_at": "<UTC timestamp>",
  "version": 1
}
```

The `nutrition` map is the total consumed for this entry, not nutrition per nominal serving. Core fields are energy, protein, carbohydrates, and fat; fiber and sodium are optional because they improve hunger and scale-fluctuation explanations when known.

`source.type` distinguishes values supplied by the user, copied from a package label, obtained from an external nutrition database, published by a restaurant, calculated from a recipe, reused from a saved food, or estimated by the model. Estimated values retain uncertainty and assumptions rather than presenting guesses as exact facts.

The stable `entry_id` and `version` support editing and replacement. Removing an entry uses a conditional `DeleteItem`; replacement normally updates the same entry. If the consumed date changes, the service atomically moves the item to the new date-based sort key. Historical recipe entries retain their nutrition snapshot even if the recipe is later edited.

Daily totals and period averages query the relevant `INTAKE#<local-date>` key range and sum the nutrition maps in Python. `food_fingerprint` lets the service group recent entries to identify frequently eaten foods without relying on exact capitalization or wording.

### 4. Saved Food

```text
PK = USER#<user-id>
SK = SAVED_FOOD#<food-id>
```

```json
{
  "record_type": "saved_food",
  "food_id": "<uuid>",
  "name": "My usual Greek yogurt",
  "aliases": ["usual yogurt"],
  "default_serving": {
    "quantity": 170,
    "unit": "g"
  },
  "nutrition_per_serving": {
    "energy_kcal": 100,
    "protein_g": 17,
    "carbs_g": 6,
    "fat_g": 0
  },
  "source": {
    "type": "package_label",
    "provider": null,
    "external_id": null,
    "source_url": null
  },
  "updated_at": "<UTC timestamp>",
  "version": 1
}
```

Saved foods provide fast, repeatable logging. Frequently eaten foods are initially computed from recent intake entries using `food_fingerprint`; users may promote a frequent item into a saved food. This avoids maintaining counters that can become incorrect when historical food entries are edited or removed.

### 5. Recipe

```text
PK = USER#<user-id>
SK = RECIPE#<recipe-id>
```

```json
{
  "record_type": "recipe",
  "recipe_id": "<uuid>",
  "name": "Turkey chili",
  "yield": {
    "servings": 6,
    "serving_description": "one sixth of the recipe"
  },
  "ingredients": [
    {
      "name": "Lean ground turkey",
      "quantity": 900,
      "unit": "g",
      "nutrition_for_quantity": {
        "energy_kcal": 1350,
        "protein_g": 180,
        "carbs_g": 0,
        "fat_g": 72
      },
      "source": {"type": "external_database", "external_id": "<optional>"}
    }
  ],
  "nutrition_total": {
    "energy_kcal": 1350,
    "protein_g": 180,
    "carbs_g": 0,
    "fat_g": 72
  },
  "nutrition_per_serving": {
    "energy_kcal": 225,
    "protein_g": 30,
    "carbs_g": 0,
    "fat_g": 12
  },
  "calculation_version": 1,
  "updated_at": "<UTC timestamp>",
  "version": 1
}
```

The recipe stores ingredient-level calculation inputs, total nutrition, and per-serving nutrition so results can be explained and recalculated. The application limits recipe size so one recipe remains safely representable as one DynamoDB item. A logged serving becomes a normal intake entry with a `recipe_id` source reference and a copied nutrition snapshot.

### 6. Hydration Entry

```text
PK = USER#<user-id>
SK = HYDRATION#<local-date>#<consumed-at-UTC>#<entry-id>
```

```json
{
  "record_type": "hydration",
  "entry_id": "<uuid>",
  "local_date": "2026-09-14",
  "consumed_at": "2026-09-14T15:00:00Z",
  "amount_ml": 500,
  "beverage_name": "water",
  "notes": null,
  "updated_at": "<UTC timestamp>",
  "version": 1
}
```

Individual entries support logging, editing, and removing drinks. A day's hydration total is calculated by querying that day's `HYDRATION#` prefix. The current hydration target comes from the applicable nutrition strategy.

### 7. Planned Meal or Food Decision

```text
PK = USER#<user-id>
SK = PLANNED_MEAL#<local-date>#<meal-slot>#<entry-id>
```

```json
{
  "record_type": "planned_meal",
  "entry_id": "<uuid>",
  "local_date": "2026-09-15",
  "meal_slot": "dinner",
  "scheduled_at": "2026-09-16T00:00:00Z",
  "status": "planned",
  "context": {
    "type": "restaurant",
    "venue_name": "Example Restaurant",
    "event_description": null
  },
  "items": [
    {
      "name": "Grilled chicken plate",
      "serving_description": "one entree",
      "recipe_id": null,
      "saved_food_id": null,
      "nutrition": {
        "energy_kcal": 520,
        "protein_g": 48,
        "carbs_g": 45,
        "fat_g": 18
      },
      "source": {"type": "restaurant_official", "source_url": "<optional>"}
    }
  ],
  "alternatives": [
    {"name": "Swap fries for vegetables", "reason": "More volume and fiber"}
  ],
  "recommendation_summary": "High-protein dinner that fits the remaining intake context.",
  "strategy_effective_from": "2026-09-14T00:00:00Z",
  "source_conversation_id": "<conversation-id>",
  "completed_intake_entry_ids": [],
  "updated_at": "<UTC timestamp>",
  "version": 1
}
```

Only recommendations the user chooses to save or schedule become planned-meal records. Unaccepted suggestions remain in the S3 conversation snapshot. `context.type` supports ordinary meals, restaurants, eating out, and social events without separate entity types. Date-keyed items support day or range retrieval, and each planned meal can be independently replaced, completed, skipped, or deleted.

There is no overarching meal-plan ID. A multi-day plan is the set of planned-meal entries across its date range. This keeps individual meals independently editable and avoids introducing a container the product does not otherwise need.

### 8. Progress and Well-Being Check-In

```text
PK = USER#<user-id>
SK = CHECKIN#<local-date>#<recorded-at-UTC>#<entry-id>
```

```json
{
  "record_type": "checkin",
  "entry_id": "<uuid>",
  "local_date": "2026-09-14",
  "recorded_at": "2026-09-14T13:00:00Z",
  "measurements": {
    "weight_kg": 80.8,
    "body_fat_percent": 18.5,
    "body_fat_source": "user_estimate",
    "waist_cm": null
  },
  "subjective": {
    "hunger": 7,
    "energy": 5,
    "recovery": 6,
    "food_fixation": 8,
    "cravings": [
      {"food": "salty snacks", "intensity": 7}
    ],
    "body_image_note": "Feeling discouraged by abdominal definition today"
  },
  "context_tags": ["evening_hunger", "poor_sleep"],
  "notes": null,
  "updated_at": "<UTC timestamp>",
  "version": 1
}
```

Ratings use a validated 1-to-10 scale when present. Every measurement and subjective field is optional, allowing a user to report only what is relevant. Body-fat values are explicitly labeled by source, and body-image data is text supplied by the user; this design includes no image or computer-vision processing.

Check-ins support progress trends, hunger and energy analysis, scale-fluctuation explanations, and target adjustments. They are queried alongside intake and hydration records for the same period.

### 9. Confirmed Behavior Pattern

```text
PK = USER#<user-id>
SK = BEHAVIOR_PATTERN#<pattern-id>
```

```json
{
  "record_type": "behavior_pattern",
  "pattern_id": "<uuid>",
  "category": "nighttime_snacking",
  "description": "Frequently snacks on nuts after dinner when still awake late.",
  "status": "confirmed",
  "user_confirmed": true,
  "triggers": ["late_night", "easy_access_to_problem_food"],
  "foods": ["nuts"],
  "strategies": [
    {
      "type": "portioning",
      "description": "Pre-portion one serving instead of eating from the container."
    },
    {
      "type": "substitution",
      "description": "Use a higher-volume snack when physical hunger remains."
    }
  ],
  "first_observed_at": "<UTC timestamp>",
  "last_observed_at": "<UTC timestamp>",
  "evidence_window_days": 30,
  "source_conversation_id": "<conversation-id>",
  "updated_at": "<UTC timestamp>",
  "version": 1
}
```

This record carries durable coaching knowledge across separate conversations. The agent may identify a candidate pattern from check-ins and intake, but it should not write a `confirmed` pattern without the user's agreement. Strategies may cover portioning, substitution, meal timing, environmental changes, or avoiding compensatory restriction. Resolved patterns remain available with `status = resolved` so the system does not repeatedly rediscover them.

### 10. Conversation Metadata

```text
PK = USER#<user-id>
SK = CONVERSATION#<conversation-id>
```

```json
{
  "record_type": "conversation",
  "conversation_id": "<uuid>",
  "title": "Dinner planning",
  "status": "active",
  "created_at": "<UTC timestamp>",
  "updated_at": "<UTC timestamp>",
  "version": 1,
  "GSI1PK": "USER#<user-id>",
  "GSI1SK": "<updated-at>#<conversation-id>"
}
```

The conversation ID is also the Strands session ID, so an `s3_session_id` attribute would be redundant. This item proves ownership before S3 access. Its sparse global secondary index supports listing one user's conversations by most recent activity:

```text
GSI1 partition key = GSI1PK
GSI1 sort key      = GSI1SK
```

Only conversation items have these index attributes, so other user records do not consume storage or write capacity in this index.

## Access Patterns

| Operation | DynamoDB access |
| --- | --- |
| Get the user profile | Exact `GetItem` for `PROFILE` |
| Get the current strategy | Reverse `Query` on `NUTRITION_STRATEGY#`, stopping at the latest effective revision |
| Get the strategy applicable to a past date | Reverse bounded `Query` on `NUTRITION_STRATEGY#`, limited to one item |
| Get today's food log | `Query` with `begins_with(SK, "INTAKE#<local-date>#")` |
| Get intake over a period | Bounded `Query` across the relevant `INTAKE#<local-date>` keys |
| Calculate daily totals or period averages | Sum nutrition from the intake query in Python |
| Find frequently eaten foods | Group a recent intake range by `food_fingerprint` |
| List saved foods or recipes | `Query` the `SAVED_FOOD#` or `RECIPE#` prefix |
| Get hydration for a day or period | Query the corresponding `HYDRATION#` key range |
| Get planned meals for a day or period | Query the corresponding `PLANNED_MEAL#` key range |
| Get weight and well-being trends | Query the corresponding `CHECKIN#` key range |
| Get durable coaching context | Query the `BEHAVIOR_PATTERN#` prefix and select confirmed, active records |
| Verify conversation ownership | Exact `GetItem` for `CONVERSATION#<conversation-id>` |
| List conversations by recency | Reverse `Query` on `GSI1` |

These are key-based reads rather than table scans. Coaching analyses that combine intake, hydration, and check-ins perform a small number of independent user-scoped queries, which can run concurrently in the Python service.

## Feature Coverage Audit

### 1. Diet Setup

| Feature | Persistent support |
| --- | --- |
| User profile and dietary preferences | `PROFILE` stores physical inputs, dietary preferences, restrictions, allergies, dislikes, time zone, and presentation preference. |
| Starting and goal weight | The initial `NUTRITION_STRATEGY` stores baseline and goal weight; dated `CHECKIN` records store subsequent weights. |
| Weight-loss or maintenance goal | `NUTRITION_STRATEGY.goal.type` and related goal fields. |
| BMR and TDEE calculation | Each strategy stores the method, version, inputs, assumptions, and calculated BMR/TDEE. |
| Initial calorie and macro targets | The first strategy revision stores initial energy and macro targets. |
| Activity level as nutrition context | `PROFILE.activity_context` stores current context; each strategy copies the activity input used in that calculation. |

### 2. Food Tracking and Calculation

| Feature | Persistent support |
| --- | --- |
| Log, edit, remove, and replace foods | Stable `INTAKE` entries use conditional writes and deletes; nutrition and provenance are stored per entry. |
| Daily calorie and macro totals | Date-keyed intake entries are queried and aggregated; no duplicate total is required. |
| Food nutrition lookup and estimation | Lookup or estimate provenance, uncertainty ranges, and assumptions can be stored in an intake entry or saved food; unselected results remain in S3. |
| Recipe nutrition and per-serving calculation | `RECIPE` stores ingredients, total nutrition, yield, per-serving nutrition, and calculation version. |
| Saved recipes and frequently eaten foods | Recipes are durable records; frequent foods are derived from intake fingerprints and can be promoted to `SAVED_FOOD`. |
| Hydration tracking | Date-keyed `HYDRATION` entries plus the strategy's hydration target support logs and daily totals. |

### 3. Meal Planning and Food Decisions

| Feature | Persistent support |
| --- | --- |
| Meal and recipe recommendations | Recommendations remain in the S3 conversation; accepted recommendations become `PLANNED_MEAL` or `RECIPE` records. |
| New food suggestions | Suggestions remain in S3 and can become a `SAVED_FOOD` or planned-meal item when accepted. |
| Restaurant menu recommendations | S3 retains the recommendation; accepted choices use a planned meal with restaurant context and source metadata. |
| Food substitutions | S3 retains ad hoc advice; accepted substitutions can be stored as planned-meal alternatives or behavior-pattern strategies. |
| Eating-out and social-event planning | `PLANNED_MEAL.context` distinguishes restaurant and social-event plans and stores venue or event context. |
| Recommendations based on current intake and goals | The agent reads the applicable strategy plus the current date's intake and hydration records before responding. The response is retained in S3. |
| Restaurant discovery stretch goal | Discovery results are transient external results; a selected restaurant or menu item fits the existing planned-meal, saved-food, and source structures. No restaurant catalog is stored initially. |

### 4. Adaptive Diet Coaching

| Feature | Persistent support |
| --- | --- |
| Hunger, cravings, and food fixation | Structured optional fields in `CHECKIN.subjective`. |
| Nighttime snacking and recurring problem situations | Time-stamped intake/check-ins provide evidence; confirmed conclusions become `BEHAVIOR_PATTERN` records. |
| Portioning and substitution strategies | Stored in `BEHAVIOR_PATTERN.strategies` after agreement, with conversational advice retained in S3. |
| Handling missed targets and high-intake days | Compare dated intake with the strategy effective that day; coaching output remains in S3. |
| Weight and fat-loss progress | Dated check-ins store weight and optional body-fat measurements with their source. |
| Scale fluctuation interpretation | Weight check-ins are interpreted with dated carbohydrate, sodium, hydration, and intake data when available. |
| Self-reported energy, recovery, hunger, and body-image feelings | Optional structured ratings and free-text body-image notes in check-ins. |
| Muscle preservation | Strategy protein targets, intake protein totals, body measurements, and profile training context provide the required nutrition context. |
| Adjusting calorie and macro targets | Append a new strategy revision with its reason, calculation inputs, and new targets. |
| Sustainable consistency and avoiding compensatory restriction | Longitudinal intake, strategy history, check-ins, and confirmed patterns support consistency analysis; advice is retained in S3. |

Every core feature therefore has either a canonical DynamoDB representation, a deterministic calculation over canonical records, a persisted S3 conversation representation, or an accepted-output path into DynamoDB.

## Deliberately Derived Data

The initial schema does not store the following as canonical records:

- Daily calorie, macro, or hydration totals
- Weekly or monthly averages
- Calories or macros remaining today
- Current weight derived from the latest check-in
- Frequently eaten food rankings
- Weight-loss trend lines
- Scale-fluctuation explanations
- Candidate behavior patterns that the user has not confirmed

Each value can be recomputed from canonical records, preventing stale duplicated data. If measurements later show that repeated aggregation is too expensive, date-keyed summary or food-frequency items may be introduced as explicitly derived caches and rebuilt from source records.

## Consistency and Mutation Rules

Operational `REQUEST#<sha256(operation-and-idempotency-key)>` items share the
authenticated user's partition. They carry a payload digest and completed result
and are written atomically with product mutations. They are implementation
metadata, not another feature group. Reusing a key with a different payload
returns a conflict. Receipts are retained until a retention policy is chosen.

Conversation metadata may include `invocation_id` and `invocation_status`.
Conditional updates acquire exclusive invocation ownership. Failed/abandoned
invocations remain blocked pending operator reconciliation; automatic expiry
cannot safely fence a delayed S3 writer. S3 and DynamoDB commits are not atomic.
Successful message receipts preserve replay results; tools derive stable retry
keys from the trusted request and tool invocation identity.

Conversation metadata also stores an internal `has_snapshot` marker to detect
missing previously committed snapshots. Operational message receipts contain
completed response text for replay; they are not a second queryable transcript.
Deleting a conversation removes its snapshot, response/create receipts and
metadata, while independent user nutrition records remain.

Historical daily targets use local end-of-day, while today's uses the current
instant. Date ranges are inclusive and limited to 366 days. Existing record dates
do not move merely because a profile timezone changes. Explicit date corrections
move the record atomically and return a new locator with the same entry ID.
Profile creation uses expected version zero. Strategy effective timestamps use
fixed UTC microsecond precision and duplicate timestamps conflict.

- Nutrition strategy revisions are append-only. A correction creates a new effective revision.
- Food, hydration, recipes, planned meals, check-ins, patterns, profiles, and conversation metadata are mutable through conditional version checks.
- Removing a food or hydration entry uses a conditional delete. Audit history is not retained unless a future requirement calls for soft deletion.
- Completing a planned meal does not automatically make it historical intake. Log consumption explicitly, then link existing intake IDs from the planned meal's local date. The service verifies those IDs belong to the same user.
- Recipe and saved-food edits never alter historical intake because logged entries contain nutrition snapshots.
- Structured facts learned in conversation are persisted only through validated tools. The model does not write arbitrary DynamoDB items.

## Cost and Scale Implications

- S3 stores one mutable latest snapshot per conversation rather than an immutable object per turn, reducing storage and request volume while preserving resumability.
- DynamoDB reads use exact keys or bounded user-scoped queries; table scans are not part of normal product behavior.
- Daily summaries and frequency rankings are calculated from source data initially, avoiding extra writes and consistency maintenance.
- Only conversation metadata is copied into the sparse GSI, keeping index storage and write amplification limited.
- A personal nutrition history is expected to remain a modest user partition. If future usage or analytics become substantially different, the access patterns and database choice must be reevaluated rather than forcing new workloads into this schema.

## Security and Privacy Constraints

- Cognito authentication determines the partition key; clients and tools cannot select another user's partition.
- Only the backend IAM role can access the table and S3 bucket.
- The S3 bucket remains private, blocks public access, and uses encryption in transit and at rest.
- DynamoDB encryption and least-privilege IAM apply to canonical user data.
- When these resources are provisioned, enable S3 access logging, relevant CloudTrail data events, and CloudWatch metrics; retain only the observability data that justifies its additional storage and event-recording cost.
- Body-image information is user-provided text only. No image-based body analysis is represented or planned.
- Sensitive profile and health-adjacent fields should not be included in application logs.

## References

- [DynamoDB core components](https://docs.aws.amazon.com/amazondynamodb/latest/developerguide/HowItWorks.CoreComponents.html)
- [DynamoDB data-modeling building blocks](https://docs.aws.amazon.com/amazondynamodb/latest/developerguide/data-modeling-blocks.html)
- [DynamoDB condition expressions](https://docs.aws.amazon.com/amazondynamodb/latest/developerguide/Expressions.ConditionExpressions.html)
- [Amazon S3 security best practices](https://docs.aws.amazon.com/AmazonS3/latest/userguide/security-best-practices.html)
