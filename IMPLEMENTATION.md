# Backend implementation audit and staged plan

## Review cycle - 2026-09-15

Baseline: main at `4a000e3`, origin `git@github.com:psurge1/ImHungry.git`.
Preserve untracked BLOG_POST.md and skills-lock.json. Read all 13 project Markdown
files, inspected backend/frontend/tests/scripts/configuration. Baseline: 82 Python
tests, 9 frontend tests and TypeScript/Vite build passed. No standalone lint command
is configured. Offline CLI logged demo yogurt. Local Vite renders Cognito sign-in.
The documented production API command fails closed without required AWS settings;
use injected memory repositories/scripted model for this review, with no AWS changes.

### Confirmed issue ledger

| ID | Severity | User impact | Reproduction | Root cause | Proposed fix | Regression test |
| --- | --- | --- | --- | --- | --- | --- |
| R1 | medium | Invalid links produce service failures | GET food-log locator encoding a numeric UUID returns 503 | Decoded locator types are unchecked | Validate locator shape/types | Malformed JSON locators return 422 |
| R2 | medium | Browser cannot read unexpected API errors | Inject service exception; response lacks CORS and request ID headers | Fallback handler runs outside middleware | Handle failures inside request middleware, apply outer CORS | Allowed/untrusted origins on 503 |
| R3 | high | Future meals and historical check-ins disappear | Plans/check-ins lists omit date range; backend defaults to today | Frontend does not request history/future dates | Explicit selectable bounded ranges | Assert list paths and browser fixture visibility |
| R4 | high | Retrying a saved food/drink/plan can duplicate it | api() generates a fresh POST key on every retry | Form retry lacks stable operation identity and timestamp | Retain exact API request after ambiguous failure | Simulated lost response, stable payload/key |
| R5 | medium | Clearing profile fields silently keeps old values | Blank height/DOB/sex/activity then save | Blank inputs omitted from PATCH | Send explicit nulls | Clear populated optional profile fields |
| R6 | medium | Old proposed targets remain accept-able after editing goal | Calculate, edit weight, accept without recalculating | Preview not invalidated on goal edits | Clear preview on form changes | Proposal disappears after input change |
| R7 | medium | Replaced food retains previous source and optional nutrients | Edit sourced food with sodium/fiber; nested PATCH merges metadata | Manual editor sends incomplete replacement | Explicitly clear source metadata and unsupported nutrient fields on replacement | Inspect replacement PATCH and stored record |
| R8 | medium | Backdated food/drink can land on a different day | Device/profile time zones differ; form constructs device-local noon | Timestamp ignores profile timezone | Convert selected date using profile timezone | Extreme offsets/DST date roundtrip |
| R9 | medium | Failed conversation request loses retry identity when leaving Coach | Send fails, switch tabs, return | Coach unmount discards pending request | Preserve Coach while switching tabs; reuse create request too | Fail, switch tabs, retry with same key |

No critical issue established. No production user data was read or changed.

### Stages

1. **API boundaries:** services.py, api.py, API/CORS tests. Accept malformed
   locators as 422; sanitized unexpected errors retain CORS/request ID. Run focused
   API/CORS tests, full Python/frontend suites, build. Commit: `stage 1: harden API error boundaries`.
2. **Core frontend reliability:** App.tsx, api.ts, units/date helpers, component/API
   tests. Fix R3-R9; dates, history, replacement and retries behave consistently.
   Run focused regressions, both full suites, build and local browser flows using
   disposable fixtures. Commit: `stage 2: fix tracking history and retry reliability`.
3. **Verification and docs:** correct local-run/verification notes and record final
   feature coverage, remaining limitations and browser results here. Re-run full
   checks for the final tree; commit `stage 3: document review verification and limits`.

Each stage includes diff review, `git diff --check`, commit and push to main.
No provisioning, IAM, infrastructure deployment or credential changes in this cycle.

### Improvement ideas / deferred work

- Low: smaller frontend bundle; current build warns about its size. No runtime
  defect established, so dependency restructuring is deferred.
- General food database, broader restaurant retrieval and low-obsession presentation
  remain documented gaps. They require product/provider choices beyond this bug cycle.
- Production authentication/model quality and conversation failure recovery remain
  external verification/operational work; do not weaken authentication or auto-unlock.

### Review checkpoints

- Stage 1: R1/R2 reproduced with failing regressions, then fixed. Focused API/CORS
  group 12 passed; full Python 89 passed; frontend 9 passed; TypeScript/build pass.
  Normal local frontend sign-in rendered in browser; API failure paths exercised
  through TestClient with both memory and Moto repositories. No live AWS checks.
  Commit `8af3e82` pushed to origin/main.
- Stage 2: R3-R9 fixed in App.tsx and the date helper, with frontend regressions
  and backend persisted-null/replacement tests. Full Python 93 passed, frontend
  20 passed, TypeScript/build passed; only existing AnyIO and bundle-size warnings.
  A disposable local browser harness used the real App/FastAPI/services/Strands
  loop with memory data, a scripted model and an injected test verifier, outside
  the repo. Verified future-plan/history visibility, check-in creation, target
  preview invalidation/acceptance, food replacement/totals, hydration and coach
  tool logging. Today/Plans fit a 390px viewport; switching tabs preserves forms.
  API logs showed successful preflight and product requests. No new application
  console errors after correcting the temporary harness's module imports.
  Lost-response retries, profile clearing, source cleanup and extreme timezone/DST
  cases are regression-tested. Production auth and real model quality were not
  exercised. Pending requests remain in memory only; reloading/signing out or
  replacing a form discards them. Reconcile existing entries before resubmitting.


## Audit (2026-09-14)

Read in authority order: FEATURES.md, ARCHITECTURE.md, SCHEMA.md,
ToolsAndEndpoints.md, AGENTS.md, README.md. These are all project Markdown
files at audit time. Baseline: nine passing tests; Python 3.12.13,
strands-agents 1.55.1, boto3/botocore 1.43.93, Pydantic 2.13.5.
ToolsAndEndpoints.md and skills-lock.json were initially untracked user files.
The interface specification is included as an input to this work; the unrelated
skill lock is preserved without committing it.

### Findings and resolutions

1. ARCHITECTURE.md predates SCHEMA.md: PLAN#CURRENT, plan_id, FOOD#,
   entity_type, profile starting weight, and s3_session_id conflict. Adopt
   SCHEMA.md's revision timeline, INTAKE#, record_type, strategy baseline,
   and conversation_id. No plan_id is needed.
2. The baseline supplies an invented profile and nutrition baseline, globally
   shared food state, no dates, and no authorization. Replace them with
   user-scoped services, explicit missing context, and empty real totals.
3. The schema supplies DOB/sex/height, provenance, subjective ratings, planned
   decisions, and confirmed patterns missing from the old architecture. Domain
   validation must retain optional unknowns and require all four core nutrition
   values. Calculations report missing inputs; no invented BMR inputs.
4. Date edits change physical keys; conditional single writes are insufficient.
   Use atomic transactions for moves and create-plus-idempotency receipts.
   Profile bootstrap uses expected version zero. Same-effective-time strategy
   revisions conflict; no silent overwrite. Nested patches merge recursively.
5. Idempotency and conversation locking are promised but have no schema.
   Add operational REQUEST# receipts and conversation invocation lock fields,
   without another product feature group. Receipts bind operation and payload.
   Automatic expired-lock takeover cannot safely fence an in-flight S3 write:
   failed/abandoned turns remain blocked for explicit operator reconciliation.
   This trades availability for avoiding duplicate writes or lost snapshots.
6. DynamoDB Query is paginated at 1 MB; list and aggregate reads must consume
   every page. Public lists have cursors; aggregations cap ranges at 366 days.
   Latest weight must skip check-ins without weight. Strategies for a historical
   day use the user's local end-of-day; today's uses the current instant.
   Dates already recorded retain their original local date after timezone edits.
7. Opaque resource references encode only a validated type/date/time/UUID
   locator. They are not authorization: every lookup constructs the partition
   from verified identity. Cursor scope is checked against the query.
8. FastAPI and @tool functions are sibling adapters, never CRUD calls through
   tools. Production verifies Cognito access-token signature, issuer, expiry,
   token_use and client_id; client-supplied identity headers are ignored.
   Tests inject a verifier and repositories without accessing AWS.
9. Installed Strands supports ToolContext, invocation_state, idempotency_token,
   SnapshotSessionManager and S3Storage. Pin the tested SDK. Its native key and
   JSON shape match the frozen S3 decision; no redesign is necessary. Configure
   invocation snapshot timing explicitly; expose only user/assistant text.
   SDK idempotency alone is not durable HTTP replay protection.
10. S3 and DynamoDB cannot share a transaction. A turn that partially fails
    may have committed tool writes; do not automatically rerun it. Record
    pending/failed state, persist completed response receipts, and document
    operator recovery. Conversation deletion excludes concurrent invocation.
11. External nutrition/menu providers are unspecified. Supply injectable
    provider contracts and explicit unavailable errors until selected. Model
    estimates are validated, labeled, and never logged automatically. Restaurant
    advice can use user-provided menu details; discovery remains deferred.
12. Completing a planned meal does not imply consumption. Explicitly logged
    intake IDs may be linked after verifying ownership. Historical recipe/log
    snapshots remain independent. Missing log days are not evidence of fasting.
13. Existing dependencies omit FastAPI/server/auth/test support. Add only the
    runtime and local testing libraries needed. No AWS resources, IAM, deployment,
    frontend, MCP, RAG, or additional agent architecture are part of this work.
14. Numerical examples also needed correction: the strategy's sample BMR/TDEE
    did not match its inputs, and the recipe's totals did not match its single
    listed ingredient. Both examples now match deterministic calculation. The
    Mifflin-St Jeor equation was checked against its original publication.

SDK APIs were inspected in the installed source. References:
[Strands snapshot manager](https://strandsagents.com/docs/api/python/strands.session.snapshot_session_manager/),
[Cognito verification](https://docs.aws.amazon.com/cognito/latest/developerguide/amazon-cognito-user-pools-using-tokens-verifying-a-jwt.html).
[Mifflin-St Jeor equation](https://pubmed.ncbi.nlm.nih.gov/2305711/).

## Feature coverage matrix

All endpoint paths below are under /v1. Detailed fields remain in SCHEMA.md.

| Feature | Persisted data | Python service | Strands tool | FastAPI endpoint | Tests |
| --- | --- | --- | --- | --- | --- |
| Profile, preferences, activity | PROFILE | NutritionService | get/update_user_profile | /profile | service, API, isolation |
| Starting/goal weight, loss/maintenance | NUTRITION_STRATEGY.goal | NutritionService | calculate/save_nutrition_strategy | /nutrition-strategies | strategy history |
| BMR/TDEE, initial/adjusted macros | strategy calculation/targets | NutritionService | calculate/get_nutrition_strategy | /nutrition-strategies/calculate, /current | arithmetic, missing inputs |
| Log/edit/remove/replace foods | INTAKE | NutritionService | log/edit/remove_food | /food-log | CRUD, move, retry, isolation |
| Daily totals/period averages | derived intake and dated strategy | NutritionService | get_food_log/get_nutrition_summary | /nutrition-summary | dates, targets, unknowns |
| Nutrition lookup/estimation | source/estimate on accepted intake | NutritionService/providers | lookup/estimate_food_nutrition | /foods/search, /estimate | provider fakes, validation |
| Recipe totals/per-serving, saved recipes | RECIPE | NutritionService | calculate/save/update/get_recipes | /recipes | arithmetic, history independence |
| Saved/frequent foods | SAVED_FOOD, derived fingerprints | NutritionService | save_food/get_saved_and_frequent_foods | /saved-foods, /foods/frequent | grouping, edits/deletes |
| Hydration | HYDRATION, strategy target | NutritionService | log/edit/remove_hydration, get_hydration_summary | /hydration, /hydration-summary | totals, targets, moves |
| Meal/recipe/new-food suggestions, substitutions | S3; accepted PLANNED_MEAL | NutritionService, ConversationService | get_meal_decision_context | /conversations/{id}/messages | real Strands loop with fake model |
| Restaurant menu advice, eating out, social events | S3, planned meal context | NutritionService/providers | lookup_restaurant_menu, planned-meal tools | /restaurant-menus/search, /planned-meals | unavailable provider, saved context |
| Recommendations using intake/goals | derived profile/strategy/intake context | NutritionService | get_meal_decision_context | conversation messages | context and identity |
| Hunger/cravings/fixation, energy/recovery/body image | CHECKIN | NutritionService | log/update_checkin | /check-ins | optional ratings, validation |
| Night snacking, portioning, recurring situations | BEHAVIOR_PATTERN | NutritionService | get/save/update_behavior_pattern | /behavior-patterns | confirmation, status, CRUD |
| Progress, fluctuations, muscle preservation | check-ins, intake, profile, strategy | NutritionService | get_progress_context | /progress-summary | weight gaps, trends, adherence |
| Missed targets, consistency, no compensation | source context + S3 advice | ConversationService | get_progress_context | conversation messages | prompt rules, context |

## Staged implementation plan

Every stage begins with git status/diff review and ends with focused tests,
`UV_CACHE_DIR=/tmp/imhungry-uv-cache uv run pytest -q`, `git diff --check`,
final diff/secret-path review, commit and push to origin/main. No live AWS tests.

| Stage | Scope and files | Acceptance criteria / focused validation | Intended commit |
| --- | --- | --- | --- |
| 0 | Audit/plan; ARCHITECTURE.md, SCHEMA.md, ToolsAndEndpoints.md, IMPLEMENTATION.md | Documents agree; frozen S3 section unchanged; baseline tests pass | docs: reconcile backend specifications and stage implementation |
| 1 | src/imhungry/models.py, repository.py, errors.py; pyproject.toml, uv.lock; repository/model tests | Validated records, user partitions, atomic version checks/moves/retries; fake and DynamoDB contract tests | feat: add validated domain and transactional repositories |
| 2 | services.py, api.py, auth.py, tool adapters; core tests | Profile, strategy, food CRUD and summaries through sibling HTTP/tools; isolation, date/history, validation, Cognito verifier tests | feat: implement authenticated nutrition tracking vertical slice |
| 3 | Remaining service/models/routes/tools/provider adapters; feature tests | Recipes, saved/frequent foods, hydration, planning, check-ins, progress, patterns and estimation; complete local feature tests | feat: add meal planning and adaptive nutrition services |
| 4 | conversations.py, runtime.py, agent.py, main.py; session/integration tests; README and audit updates | Native snapshots restore; actual Strands loop selects tools using fake model; locks/replay/errors; sanitized messages; CLI smoke; full suite | feat: persist Strands conversations and document backend operation |

## Checkpoints

Updated as stages complete. This milestone ends after Stage 4 verification.

- Stage 0: baseline 9 tests passed; documentation committed and pushed as 2ff3b6a.
- Stage 1: domain validation and both repository adapters tested locally,
  including atomic conflicts/moves, sparse index, all-page reads, and isolation.
  Runtime dependencies are locked; Moto is a development-only AWS emulator.
- Stage 1 committed and pushed as d7f2ab8; full suite: 22 passed.
- Stage 2: profile/strategy/food services, FastAPI and trusted-context tools;
  Cognito verification is tested with ephemeral local signing keys. Local tests
  cover identity, replay, validation, timezone corrections and historical targets.
- Stage 2 committed and pushed as a72dc0d; full suite: 35 passed.
- Stage 3 adds all remaining canonical resource adapters and nutrition context.
  Estimation uses Strands BedrockModel.structured_output directly, without a second
  agent. External database/menu implementations remain unconfigured contracts.
  Period target aggregation uses two bounded timeline queries, not one per day.
- Integration finding: Strands 1.55.1's tool validator calls model_dump(), so
  nested Pydantic arguments reach tool functions as dictionaries, including
  Python field names for aliases. The shared tool adapter reconstructs those
  validated domain models before invoking services. Direct-call tests alone
  would not catch this; the real Strands loop test does.
- Stage 3 committed and pushed as 57793e9; full suite: 59 passed.
- Stage 4: native S3 snapshot lifecycle, durable message replay and exclusive
  conversation writes; fail-closed partial failures and missing snapshots;
  production runtime composition; explicit offline/Bedrock CLI modes. Legacy
  globally shared mock tools and their seven baseline-only tests were removed.
  The current suite has 77 passing tests, including every one of the 34 tools
  through Strands' adapter. Focused final integration group: 23 passed. Offline
  CLI recommendation and `git diff --check` pass. One upstream Starlette/AnyIO
  deprecation warning remains; no application warnings or failing tests.
  The interactive offline CLI also passes greeting -> food logging -> dinner
  context. All 57 documented HTTP operations are present, and OpenAPI generation
  succeeds. No live model calls were made.

## Completion boundaries

The four feature groups now have canonical persistence, shared services, tool
adapters and HTTP contracts, with suggestions/coaching flowing through the single
conversation agent. No fifth group or plan ID was introduced. S3's frozen native
schema and key layout are unchanged. Operational response receipts and fail-closed
conversation coordination are explicitly documented additions to DynamoDB.

Deferred at the end of that milestone: an external food database and restaurant-menu
provider, restaurant discovery, the second presentation experience, and live AWS
deployment/verification. See the follow-up stages below for subsequent work.
Bedrock structured estimation is implemented and fake-model-tested.
Tests prove orchestration, not the quality of live model recommendations.

README.md contains local run commands, resource requirements and a partial-failure
recovery procedure. `skills-lock.json` remains the user's untracked file, unchanged.
No live AWS calls, resource creation, IAM edits, secrets or .env files were used
during stages 1 through 4. Stage 4 ended that implementation milestone.


## Follow-up: restaurant providers and AWS deployment

- Commit `ebf99bf` added public restaurant menu retrieval and structured estimation
  fallback. General food database integration remains deferred.
- Following explicit user authorization, two CloudFormation stacks provisioned
  the required persistent resources and the Lambda/API Gateway backend in
  `us-west-2`. Infrastructure, build scripts, deployment safeguards and resource
  configuration are documented in `infra/README.md`.
- `infra/DEPLOYMENT.md` records the live endpoint, Cognito identifiers, checks
  performed and the remaining authenticated conversation verification boundary.
- Both stacks completed, the public health endpoint and authorization rejection
  checks passed, and a live Bedrock model call succeeded. The application suite
  remains at 80 passing tests. No frontend or additional product feature group
  was introduced.
