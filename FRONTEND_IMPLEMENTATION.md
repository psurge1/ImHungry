# Frontend implementation

Keep the interface small; the existing backend owns nutrition logic and persistence.

1. [x] Add a React/TypeScript app in `frontend/`, with Amplify sign-in, sign-up,
   verification and password recovery using the existing Cognito pool.
2. [x] Connect Today, Setup, Coach, Plans and Progress to real backend endpoints.
   Show loading/errors and use request IDs and record versions for writes.
3. [x] Add Amplify Hosting and restrict backend CORS to the deployed frontend
   plus localhost development. Keep infrastructure in the same repository.
4. [x] Build, test key API/auth flows, deploy, check the live site and CORS,
   and record the URL and short run/update commands.

Live app: https://main.d2sqqpgd3gb3c4.amplifyapp.com

Initial deployment verification: six frontend tests, 82 backend tests, TypeScript/production build,
dependency audit, hosted sign-in/sign-up/password-recovery screens, live allowed
preflight and gateway error headers, and rejected untrusted origins. Signed-in
profile and message workflows are covered with mocked component/API tests; a real
email-verified user conversation remains a manual check.

Review on 2026-09-15: 20 frontend tests, 93 backend tests and TypeScript/build pass.
Fixed history ranges, stable retries across tabs, profile clearing, stale target
previews, food replacement metadata and profile-timezone backdating. Local browser
checks used disposable data and a scripted coach; no AWS deployment was performed.
Details and the issue ledger are in [IMPLEMENTATION.md](IMPLEMENTATION.md).
