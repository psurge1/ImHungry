# Development deployment

Provisioned and verified on 2026-09-14 in `us-west-2` using the user-authorized AWS CLI session.

Both CloudFormation stacks completed successfully:

- `imhungry-dev-foundation`
- `imhungry-dev-backend`

API base URL: [https://kud8sdryy0.execute-api.us-west-2.amazonaws.com/dev](https://kud8sdryy0.execute-api.us-west-2.amazonaws.com/dev)

Health check: [GET /health](https://kud8sdryy0.execute-api.us-west-2.amazonaws.com/dev/health)

## Application configuration

These are public identifiers and resource names, not credentials.

```text
AWS_REGION=us-west-2
IMHUNGRY_ENV=dev
IMHUNGRY_TABLE=imhungry-dev-foundation-Table-12ZBQ9VNFQ9HD
IMHUNGRY_BUCKET=imhungry-dev-foundation-bucket-mj87uea7hpsc
COGNITO_ISSUER=https://cognito-idp.us-west-2.amazonaws.com/us-west-2_pvA4Z82k5
COGNITO_CLIENT_ID=2cm2uoqc3e5nc9lmaisqejqg9r
COGNITO_USER_POOL_ID=us-west-2_pvA4Z82k5
STRANDS_MODEL_ID=global.amazon.nova-2-lite-v1:0
```

Backend function: `imhungry-dev-backend-Backend-ZBd0jBa2EaNW`.

CloudWatch log group: `imhungry-dev-backend-FunctionLogs-lYhAV3f9mcEa`.

## Verification

- foundation stack complete.
- backend stack complete.
- Lambda active.
- Public health returns 200.
- Gateway rejects missing and invalid access tokens.
- Cognito signing keys published.
- DynamoDB table and GSI1 active with deletion protection.
- S3 encryption and all public-access blocks enabled.
- IAM simulation allows runtime operations and denies deployment artifact access.
- One live Bedrock Converse call to the configured model succeeded.
- Both templates passed cfn-lint, custom CloudFormation Guard rules, and AWS change-set validation.
- All 80 existing application tests passed.

The public health probe also exercised the deployed Linux ZIP, Lambda Web Adapter,
FastAPI initialization and API Gateway streaming integration. The Bedrock call was
made with the deploying identity; runtime role permissions were checked by IAM
simulation. No authenticated user session or full deployed conversation round trip
was exercised. No user passwords or tokens were created, collected or stored.

To repeat the read-only deployed checks:

```bash
uv run python scripts/verify_deployment.py
```

See [deployment instructions](README.md) for repeatable builds, updates, retention
choices and authentication setup. Cognito SDK sign-up/sign-in uses the pool and
public client above; backend requests require the resulting access token.
No dashboard changes were needed for this deployment.

## Frontend deployment

The subsequent frontend deployment is live at
https://main.d2sqqpgd3gb3c4.amplifyapp.com (Amplify app `d2sqqpgd3gb3c4`, branch
`main`, CloudFormation stack `imhungry-dev-frontend`). The frontend uses the Cognito
pool and client above and requires no hosted-login callback.

The backend was updated with exact-origin CORS for this URL and localhost:5173.
OPTIONS preflight is unauthenticated; product requests remain authenticated.
Live preflight and unauthorized-response CORS headers were verified. Amplify
published successfully and sign-in, account creation and recovery screens render.
See [frontend guide](../frontend/README.md) for local development and publishing.

## Review status - 2026-09-15

The subsequent review used local fixtures only and did not redeploy or reverify
AWS resources. Its code changes were committed separately; Git pushes do not
automatically publish the frontend or backend. The verification results above
describe the earlier deployment, not the latest repository revision.

## Explicit application deployment - 2026-09-15

Deployed application revision `4d88100` after the user's explicit instruction:

- Backend change set `app-1789483627`: `UPDATE_COMPLETE`. Only Lambda code and
  dependent API integration references changed; no replacements or IAM changes.
- Backend ZIP SHA256: `6b50c2ab901a0725c3c51866221c78a36e28cff07c142c19662378f560dd85a5`.
  Lambda's reported code checksum matches the local artifact.
- Amplify app `d2sqqpgd3gb3c4`, branch `main`, job `4`: `SUCCEED`.
  Published `/assets/index-B6YajPyQ.js` matches the local frontend build byte-for-byte.
- Health, missing/invalid-token rejection, signing keys, storage protection and
  runtime IAM simulation passed `scripts/verify_deployment.py`.
- Live preflight accepts the Amplify origin (200) and rejects an untrusted origin
  (400, no allow-origin header). The deployed sign-in page rendered in the browser.
- No real-user authenticated HTTP conversation was exercised.

### Restaurant provider verification

The actual `lookup_restaurant_menu` tool was exercised locally against public
sources with disposable data. For Chuy's and Torchy's Tacos, the guessed base
MenuMacros URLs returned 404, category URLs returned 200 but yielded no parsed
items, and Macros.Menu returned 429. Both lookups returned the explicit estimation
fallback. A 200 page response therefore does not establish a successful lookup.

A real Bedrock/Strands coach probe invoked `lookup_restaurant_menu` followed by
`estimate_food_nutrition`, including a probe at the deployed 3000-token limit.
The estimation calls returned generic validation errors despite valid-looking
request arguments. Separate direct structured-estimation requests and an isolated
Strands tool-adapter call did validate; this does not establish reliable behavior
inside a full coach turn. The conversational fallback needs a separate fix.
These probes used the local AWS identity and memory repositories, not production
user records or the deployed Cognito HTTP flow.

There is no general Google/web search tool or arbitrary official-site scraper.
The adapter tries guessed MenuMacros/Macros.Menu paths, or sends a supplied HTTPS
menu URL through Macros.Menu. It does not guarantee both sites are called when an
earlier source succeeds. The direct frontend Estimate form calls estimation
without restaurant lookup. Conversation responses project text only, so the UI
does not show tool-call activity. No provider functionality was changed by this
deployment; successful published restaurant nutrition retrieval is not verified.
