# ImHungry Architecture

## Status

This document defines backend boundaries. SCHEMA.md is authoritative for persistence and ToolsAndEndpoints.md for interfaces. IMPLEMENTATION.md records staged delivery.

## Overview

```text
Client ──sign in──► Cognito User Pool
   │                    │
   │ ◄───── JWT ────────┘
   │
   └──authenticated request──► API Gateway ──► FastAPI Backend
                                                        │
                           ┌──non-conversational work───┐
                           │                            │
                           │                            ▼
                           │                    Python Services ──► DynamoDB
                           │                            ▲
                           ▼                            │
                     Strands Agent ──► Local Tools ─────┘
                        │     │
          model calls   │     │ load/save conversation
                        ▼     ▼
                    Bedrock   S3
```

The client signs in through Amazon Cognito and sends its JWT with each request. API Gateway validates the token and forwards the authenticated request to the Python FastAPI backend. For a conversational request, the backend restores the user's Strands session from S3, invokes the agent with Amazon Bedrock Nova, and exposes local Python tools to the model. The tools call the same application services used by non-conversational API operations, and those services read or update canonical product data in DynamoDB. The completed Strands session is saved back to S3 before the response is returned.

## Component Responsibilities

- **Amazon Cognito user pool:** Stores login identities and credentials and issues JWTs. Product users do not receive AWS credentials.
- **API Gateway:** Provides the managed HTTP entry point, validates Cognito JWTs, and supplies routing, CORS, throttling, and request logging.
- **FastAPI backend:** Owns request validation, authorization, application orchestration, and response models. All backend core logic is Python.
- **Strands agent:** Runs the conversational agent loop and lets the Bedrock model decide whether to call an available tool or return a response.
- **Amazon Bedrock Nova:** Performs language understanding, tool selection, nutrition estimation where appropriate, recommendations, and coaching responses.
- **Python tools and services:** Perform validated operations and deterministic calculations. Strands tools are thin adapters over application services rather than a second implementation of business logic.
- **DynamoDB:** Stores canonical product data and searchable conversation metadata.
- **Amazon S3:** Stores complete Strands conversation snapshots so sessions can continue across processes and deployments.

The backend is a modular monolith, not a collection of microservices. Its HTTP layer, agent layer, services, and persistence adapters remain separate modules, but they are developed and deployed as one Python application.

## Data Ownership

| Data | System of record |
| --- | --- |
| Login identity and credentials | Cognito |
| Nutrition profile and preferences | DynamoDB |
| Diet plans and targets | DynamoDB |
| Food logs and nutrition values | DynamoDB |
| Recipes and saved foods | DynamoDB |
| Hydration records | DynamoDB |
| Weight, hunger, energy, recovery, and body-image check-ins | DynamoDB |
| Conversation ownership, title, and timestamps | DynamoDB |
| Conversation messages, tool calls, tool results, and agent state | S3 |

Bedrock processes prompts but is not an application data store. Information mentioned in conversation history is not treated as canonical when a tool can retrieve the current value from DynamoDB.

## Storage Schemas

### S3 Conversation Snapshots

S3 stores the native Strands `SnapshotSessionManager` object rather than an ImHungry-specific transcript format. This keeps the persisted representation compatible with the installed Strands SDK and lets Strands restore the agent directly. With an `S3Storage` prefix of `imhungry/<environment>`, a server-generated conversation ID as the Strands session ID, and the stable agent ID `dietitian`, the latest snapshot is stored at:

```text
imhungry/<environment>/session/<conversation-id>/scopes/agent/dietitian/snapshots/snapshot_latest.json
```

The initial design writes only `snapshot_latest.json` after each completed agent invocation. It does not write an immutable snapshot for every turn. The latest object still contains the agent's current restorable conversation, including tool calls and results; it is session state, not a permanent audit log of every pre-summarization message.

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

`messages` uses Bedrock-style content blocks, so normal text, model-requested `toolUse` blocks, and matching `toolResult` blocks are preserved in order. `state` contains application-visible Strands agent state; the remaining state fields let Strands resume context management, interrupted work, model-specific state, and the system prompt. ImHungry treats the object as opaque framework state and does not query or partially update its JSON.

Conversation ownership does not come from the S3 key. Before opening a snapshot, the backend gets the `CONVERSATION#<conversation-id>` item from the authenticated user's DynamoDB partition; only then does it construct the fixed S3 key. The client and model never provide a bucket name, object key, Cognito user ID, or storage prefix.

### DynamoDB Application Data

The application uses one table per environment, named conceptually `imhungry-<environment>`, with string partition key `PK` and string sort key `SK`. Every user-owned item has `PK = USER#<cognito-sub>`. Timestamps are ISO 8601 UTC strings, `local_date` is `YYYY-MM-DD` in the user's saved time zone, IDs are server-generated UUIDs, and nutrition values are DynamoDB numbers (represented as `Decimal` in Python rather than binary floats).

All items include `record_type`, `schema_version`, and `created_at`. Mutable items also have `updated_at` and `version`.

| Entity | Sort key | Principal attributes |
| --- | --- | --- |
| User profile | `PROFILE` | Physical calculation inputs, preferences, restrictions, allergies, activity context, timezone and presentation preference |
| Nutrition strategy | `NUTRITION_STRATEGY#<effective-from-UTC>` | Append-only goals, baseline and goal weights, targets and calculation context; no plan ID |
| Food-log entry | `INTAKE#<local-date>#<consumed-at-UTC>#<entry-id>` | Food, serving, consumed nutrition, provenance and estimate uncertainty |
| Recipe | `RECIPE#<recipe-id>` | `name`, `servings`, ingredients, total nutrition, per-serving nutrition |
| Saved food | `SAVED_FOOD#<food-id>` | `name`, serving description, reusable calories/macros, source |
| Hydration entry | `HYDRATION#<local-date>#<consumed-at-UTC>#<entry-id>` | Amount, beverage, occurrence time |
| Planned meal | `PLANNED_MEAL#<local-date>#<meal-slot>#<entry-id>` | Accepted choices, alternatives, social/restaurant context and status |
| Progress check-in | `CHECKIN#<local-date>#<recorded-at-UTC>#<entry-id>` | Optional measurements, subjective ratings, cravings and body-image notes |
| Behavior pattern | `BEHAVIOR_PATTERN#<pattern-id>` | Confirmed recurring situations and agreed strategies |
| Conversation metadata | `CONVERSATION#<conversation-id>` | Ownership, title, status, version, timestamps and invocation coordination |

Recipes embed their ingredient list because a recipe is retrieved as one unit and expected recipes are far below DynamoDB's 400 KB item limit. If that assumption stops being true, ingredients can become separate items without changing the public service boundary. Current weight is obtained from the latest check-in; it is not duplicated as an independently editable profile field.

Only conversation metadata initially participates in a secondary index:

```text
GSI1PK = USER#<cognito-sub>
GSI1SK = <updated-at>#<conversation-id>
```

Because `GSI1PK` and `GSI1SK` are absent from all other item types, this is a sparse index used solely to list a user's conversations in recent-update order. No index is needed for the initial nutrition access patterns.

| Access pattern | DynamoDB operation |
| --- | --- |
| Get profile | Exact `GetItem` |
| Get applicable strategy | Reverse bounded `Query` of `NUTRITION_STRATEGY#` through the requested instant, limit one |
| Get one day's food log | Query the `INTAKE#<local-date>#` prefix |
| Get food logs over a date range | Bounded query over dated `INTAKE#` keys |
| Calculate daily or period averages | Query food entries for the range, then aggregate calories/macros in Python |
| Get recipe, saved food, or conversation | `GetItem` by its exact key |
| List recipes or saved foods | `Query` with the corresponding sort-key prefix |
| Get recent check-ins or latest weight | Query dated check-ins; skip entries without weight when finding latest weight |
| List conversations by recency | Query `GSI1` in descending order |

Daily summary items are not stored initially because they would duplicate food-log data and create a consistency obligation. The service calculates summaries from the user's date-keyed entries; a derived `DAILY_SUMMARY#<local-date>` cache can be introduced later only if measurements show that repeated aggregation is too expensive. A conditional update on the conversation metadata item acquires a short-lived invocation lock so two requests cannot update the same S3 snapshot concurrently.

## Per-User Data Isolation

The Cognito `sub` claim is the canonical application user ID. API clients and the model do not choose this value; it is taken from the verified JWT and passed to Strands through trusted invocation state.

DynamoDB records are grouped under a user partition such as `USER#<cognito-sub>`. Sort keys identify the record type and relevant date or ID, allowing the backend to retrieve profiles, daily food logs, recipes, check-ins, and conversation metadata with key-based queries instead of table scans.

S3 uses one private bucket and the fixed Strands key layout documented above. Before loading an S3 session, the backend verifies in DynamoDB that the conversation belongs to the authenticated user. Bucket names, object keys, storage prefixes, and user IDs are always constructed by the backend and are never accepted from the model or client.

Only the backend IAM role can access DynamoDB, S3, and Bedrock. The S3 bucket blocks public access, both stores use encryption, and IAM permissions are limited to the operations required by the backend.

## Agent and Tool Boundary

The model is responsible for interpreting natural language, deciding which context it needs, selecting tools, and producing meal recommendations or coaching responses. Python services are responsible for authorization, validation, persistence, nutrition calculations, recipe arithmetic, daily summaries, and progress calculations.

The planned tool capabilities cover:

- User profile and active diet-plan context
- Diet-plan calculations and updates
- Food nutrition lookup and estimation
- Food-log creation, editing, deletion, and retrieval
- Daily nutrition summaries
- Recipe calculation and storage
- Saved foods
- Hydration logging and summaries
- Progress check-ins and trend summaries

Meal recommendations, food alternatives, restaurant-order advice, and adaptive coaching are agent outputs built from tool-provided context; they are not separate persistence services. Food estimation may use model reasoning, but its output is structured and validated before other Python calculations consume it.

All tools are local Strands `@tool` functions. MCP is intentionally excluded because the tools are internal to one Python backend and do not yet need to be shared across applications or hosted independently.

## Persistence Choices

DynamoDB was selected because current access patterns are predictable and user-scoped: retrieve one profile, list one user's entries over a time range, retrieve recipes, and retrieve chronological check-ins. Per-user daily or weekly nutrition aggregates can be calculated in Python from date-keyed entries; precomputed daily summaries can be added later if reading raw entries becomes inefficient.

S3 was selected specifically because Strands supports persistent session snapshots there. The initial design keeps the latest snapshot for each conversation and does not retain an immutable snapshot after every turn. Concurrent writes to one conversation must be prevented so two agent invocations cannot overwrite the same session state.

## Experience Modes

Explicit tracking and low-obsession mode will use the same stored nutrition data and backend tools. A user preference will control how results are presented: explicit mode can expose calories, macros, and targets, while implicit mode can frame the same reasoning around meals, portions, hunger, energy, and habits.

## Decisions Still Open

- The compute environment that will host FastAPI, such as Lambda or a container service
- Initial conversational responses are synchronous HTTP results
- Cognito managed login versus a custom login interface
- HTTP contracts are defined in ToolsAndEndpoints.md
- The external nutrition-data source used alongside food estimation
