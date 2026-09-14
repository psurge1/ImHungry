# ImHungry

## Inspiration

Nutrition apps are good at recording numbers, but real eating decisions are more complicated. People still need help with cravings, nighttime snacking, social meals, changing hunger, and the uncertainty of estimating food from a restaurant menu. ImHungry was built to make nutrition support feel more like a practical conversation with a knowledgeable coach and less like a daily pass/fail score.

## What it does

ImHungry is an AI nutrition coach for people who want to lose weight, maintain their weight, or build more sustainable eating habits. It helps users set up a nutrition profile, calculate calorie and macro targets, log and edit food, track hydration, plan meals, save recipes and foods, record progress, and talk through difficult eating situations.

The conversational coach uses the user's current profile, goals, intake, plans, check-ins, and confirmed behavior patterns to make context-aware suggestions. Users can ask about substitutions, eating out, cravings, missed targets, or what to eat next. Restaurant menu lookup is exposed as a dedicated tool: it tries public nutrition sources such as MenuMacros and Macros.Menu, preserves the source when complete nutrition data is found, and returns a structured fallback for the coach to estimate when a menu cannot be retrieved. Estimates are labeled instead of being presented as verified nutrition facts.

The live app is available at https://main.d2sqqpgd3gb3c4.amplifyapp.com.

## How we built it

The frontend is a small React and TypeScript application hosted on AWS Amplify. Amplify Authenticator handles Cognito sign-up, email verification, sign-in, password recovery, and token refresh. The frontend sends Cognito access tokens to a FastAPI backend through API Gateway.

The backend runs as a Python Lambda application behind API Gateway. Amazon Bedrock Nova provides the language model, and Strands provides the agent loop and native conversation snapshots. The model can call validated local nutrition tools, while Python services remain responsible for authorization, deterministic nutrition calculations, validation, persistence, and mutation rules.

Canonical user data is stored in DynamoDB. Strands conversation snapshots are stored in a private encrypted S3 bucket. The backend uses optimistic versions and idempotency keys so retries do not duplicate writes, and it verifies that every record belongs to the authenticated Cognito user. Exact-origin CORS connects the deployed Amplify site and local development frontend to the API.

The source code, infrastructure templates, setup instructions, tests, and MIT license are public at https://github.com/psurge1/ImHungry.

## Challenges we ran into

The hardest part was making an AI conversation safe to combine with persistent application data. A model can recommend an action, but it must not choose a user's storage key, silently overwrite a previous strategy, or duplicate a food log after a retry. We separated the model-facing tools from the service and repository layers, used verified Cognito identity for all ownership decisions, and added version checks and durable idempotency receipts.

Conversation persistence was another challenge. Strands sessions contain model messages, tool calls, and agent state, so we used Strands' native snapshot manager with S3 instead of inventing a second transcript format. We also had to handle partial failures between DynamoDB and S3 conservatively rather than automatically replaying a turn that might already have changed user data.

Nutrition data is often incomplete or inconsistent across restaurant sites. The menu tool accepts only complete calorie, protein, carbohydrate, and fat groups, retains the source URL, and gives the coach an explicit estimation path when retrieval fails. This keeps uncertainty visible to the user.

Finally, deploying a streaming FastAPI/Lambda integration required careful API Gateway deployment ordering, gateway-level CORS responses, and a repeatable CloudFormation workflow that refuses unexpected destructive changes.

## Accomplishments that we're proud of

- Built all four product areas in scope: diet setup; food tracking and calculation; meal planning and food decisions; and adaptive diet coaching.
- Connected the same validated Python services to both REST endpoints and 34 Strands tools instead of maintaining separate business logic.
- Deployed a working authenticated web app with Amplify, Cognito, API Gateway, Lambda, Bedrock, DynamoDB, and S3.
- Added restaurant menu retrieval with source-aware structured fallback estimation.
- Preserved conversation state across backend processes with native Strands snapshots.
- Added per-user isolation, access-token verification, idempotent writes, optimistic concurrency, and explicit handling for partial conversation failures.
- Passed the backend and frontend automated test suites, CloudFormation linting, custom infrastructure checks, and live health/auth/CORS verification.

## What we learned

AI is most useful here when it interprets a user's situation and chooses the right context, while ordinary application code owns calculations and state changes. Keeping those responsibilities separate made the system easier to test and safer to evolve.

We also learned that uncertainty needs to be part of the product contract. Missing nutrition data, unlogged days, changing body weight, and incomplete restaurant pages should remain visible instead of being converted into confident-looking zeros or facts. Good coaching requires the system to know what it does not know.

## What's next for ImHungry

Next we would add a selected general food database provider, improve coverage and freshness for restaurant nutrition sources, and complete a full real-user evaluation of the hosted flow. We would also use that evaluation to refine coaching language, especially around sustainable consistency, muscle preservation, body image, and avoiding compensatory restriction.

Longer term, ImHungry could add notifications, richer progress visualizations, mobile clients, and additional presentation modes for people who prefer meal and habit guidance without seeing every calorie or macro number.
