# AWS deployment

The backend uses two CloudFormation stacks in `us-west-2` by default:

- `imhungry-dev-foundation`: on-demand DynamoDB with GSI1 and point-in-time recovery,
  one private encrypted S3 bucket, and a Cognito user pool/public app client.
- `imhungry-dev-backend`: Python 3.12 Lambda, its scoped execution role and log
  group, and a regional REST API with Cognito authorization and request throttling.

The API exposes `/health` publicly. All `/v1` routes require a Cognito **access**
token with `aws.cognito.signin.user.admin` scope, supplied by Cognito SDK sign-in.
FastAPI also checks the token's client ID, issuer, signature and purpose. ID
tokens are not accepted. Sign up and sign in through Cognito's SDK using the
deployed pool and public client; email verification is enabled. No frontend or
OAuth callback URL has been selected, so a hosted login domain is not deployed.
The public client has no client secret. Never put a password or token in Git.

Lambda Web Adapter 1.0.1 (published x86_64 layer version 28) runs the existing
Uvicorn/FastAPI app. API Gateway uses its streaming integration with a 250-second
timeout, while Lambda has 240 seconds. This avoids the buffered gateway's short
timeout for agent tool loops. The app still returns a single JSON result after
persisting the conversation; token-by-token streaming is not exposed. A timed-out
conversation retains its lock and requires the recovery process in the main README.

The function runs outside a VPC so it can reach Bedrock, Cognito public keys,
S3, DynamoDB and public menu sources without a NAT gateway. The role permits
only this table, its index, the environment's snapshot prefix, its logs and the
configured Nova model. A model-region wildcard supports global inference routing.
No provisioned concurrency or always-on compute is created. Usage of Lambda,
API Gateway, storage, point-in-time recovery, Cognito and Bedrock is billed by AWS.

The snapshot bucket also holds deployment ZIPs under `artifacts/backend/`;
the runtime role cannot access that prefix. Bucket versioning is intentionally
disabled because the agreed snapshot model stores only the latest object and
deleting a conversation must delete its stored snapshot. The table, bucket and
user pool are retained on stack deletion or replacement; table and pool deletion
protection is also enabled. Do not remove those protections without reviewing data.
Backend logs expire after 14 days. HTTP access logs and gateway payload tracing
are disabled to avoid recording user content. Basic gateway/Lambda metrics remain
available; no shared API Gateway account settings are changed.

## Build and deploy

Run from the repository root with the existing authorized AWS CLI/SDK session:

```bash
uv run python scripts/build_lambda.py
uvx --from cfn-lint cfn-lint infra/foundation.json infra/backend.json
uv run python scripts/deploy.py foundation
# Review the printed resource changes, then execute the exact change set name:
uv run python scripts/deploy.py foundation --execute app-CHANGE_SET_ID
aws cloudformation describe-stacks --stack-name imhungry-dev-foundation --region us-west-2
# Wait for CREATE_COMPLETE or UPDATE_COMPLETE before preparing the backend:
uv run python scripts/deploy.py backend
uv run python scripts/deploy.py backend --execute app-CHANGE_SET_ID
aws cloudformation describe-stacks --stack-name imhungry-dev-backend --region us-west-2
```

The builder exports the existing dependency lock with hashes and packages Linux
x86_64 wheels, not locally installed macOS libraries. Artifacts remain in ignored
`.build/`. The backend preparation uploads a content-addressed ZIP and reads
foundation outputs automatically. `--region` and `--environment` must match for
both stacks. Execution refuses resource replacements or removals; those require
manual review. A code-only update modifies the function in place. API method
changes generate a new immutable API deployment and therefore require review of
the old deployment's removal before manual execution of that change set.

`infra/security.guard` checks encrypted/private storage, retention and protection,
Cognito access-token authorization, and public app clients. It can be run with
CloudFormation Guard or the `guardpycfn` Python binding. AWS validates the change
set before execution; use `aws cloudformation describe-events --stack-name NAME
--filters FailedEvents=true --region us-west-2` to inspect failures.

Stack outputs contain the API URL, table, bucket, Cognito identifiers, execution
role, and log group. These are configuration values, not credentials. The outputs
can also configure `imhungry.runtime:app_factory` for an authorized local server.
