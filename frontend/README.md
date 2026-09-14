# ImHungry frontend

Open **https://main.d2sqqpgd3gb3c4.amplifyapp.com**. Create an account, verify the
code sent to your email, then sign in. Start with **Setup**, log a meal in
**Today**, and ask **Coach** for dinner ideas. **Plans** and **Progress** show
your saved meals, recipes, foods and check-ins.

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

## Test and update

```bash
npm test --prefix frontend
npm run build --prefix frontend
uv run python scripts/publish_frontend.py
```

The last command builds and publishes to Amplify using your existing AWS session.
This is an explicit deployment; pushing Git does not automatically publish.
The app and branch are managed by `infra/frontend.json` and the existing
`scripts/deploy.py frontend` change-set workflow.

CORS allows the Amplify URL, http://localhost:5173 and http://127.0.0.1:5173.
Gateway preflight is public; every product request still requires Cognito auth.
Gateway authorization errors expose CORS to the deployed origin. Backend responses
reflect only an approved origin. The six frontend tests use mocked API/auth responses;
they never create real users or write real nutrition data. The live sign-in screens,
hosting, preflight and unauthorized responses were checked; a complete real-user
conversation is still a manual check.
