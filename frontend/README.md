# ImHungry frontend

Open **https://main.d2sqqpgd3gb3c4.amplifyapp.com**. Create an account, verify the
code sent to your email, then sign in. Start with **Setup**, log a meal in
**Today**, and ask **Coach** for dinner ideas. **Plans** and **Progress** show
your saved meals, recipes, foods and check-ins.

Inputs use pounds, inches and fluid ounces; the backend stores metric units.
Plans initially shows today through 30 days ahead, and Progress shows the last
30 days including today. Use From/Through to inspect another range. Historical
food and drink entries use the profile timezone; meal scheduling labels device time.

React + TypeScript + Vite, Amplify Authenticator, and TanStack Query. The app uses
the existing Cognito pool and FastAPI backend. Nutrition logic stays in Python.
Amplify handles sign-up, confirmation, sign-in, password recovery and token refresh;
API requests use access tokens. Session cookies are secure on HTTPS and SameSite
Strict; they are JavaScript-readable because this is a static frontend.

## Local development

From the repository root:

```bash
npm ci --prefix frontend
npm run dev --prefix frontend
```

Open http://127.0.0.1:5173. This uses the real AWS backend and real user data.
The public app/API configuration is in `src/config.ts`, with optional `VITE_*`
environment overrides. Never put secrets in a Vite variable: they enter the bundle.

To point at a locally running, AWS-configured backend, start it using the root
README instructions with `IMHUNGRY_CORS_ORIGINS=http://127.0.0.1:5173`, then run:

```bash
VITE_API_URL=http://127.0.0.1:8000 npm run dev --prefix frontend
```

This still requires Cognito sign-in and accesses the backend's configured AWS
resources. For offline verification, use the mocked tests and root README's CLI demo.

## Test and update

```bash
npm test --prefix frontend
npm run build --prefix frontend
```

The build runs TypeScript checks. No separate lint command is configured.
When ready to publish, `uv run python scripts/publish_frontend.py` builds and
publishes to Amplify using your existing AWS session. This is an explicit
deployment; pushing Git does not automatically publish.
The app and branch are managed by `infra/frontend.json` and the existing
`scripts/deploy.py frontend` change-set workflow.

CORS allows the Amplify URL, http://localhost:5173 and http://127.0.0.1:5173.
Gateway preflight is public; every product request still requires Cognito auth.
Gateway authorization errors expose CORS to the deployed origin. Backend responses
reflect only an approved origin. The 20 frontend tests use mocked API/auth responses
and date fixtures; they never create real users or write real nutrition data.
The 2026-09-15 review exercised the actual frontend and API with disposable local
data and a scripted Strands coach. Earlier live checks covered sign-in screens,
hosting, preflight and unauthorized responses; a complete real-user conversation
is still a manual check. Review changes have not been deployed.

After a network/server failure, use **Retry same request/message** to keep the
original payload and request identity. Switching tabs preserves pending attempts.
Reloading, signing out, changing a form's identity (such as its selected date), or
starting a new conversation discards that in-memory state. Check existing records
before resubmitting after a reset. A failed server-side conversation may still
need the operator recovery described in the root README.
