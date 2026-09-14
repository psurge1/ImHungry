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
choices and authentication setup. No frontend is hosted. Cognito SDK sign-up/sign-in
uses the pool and public client above; backend requests require the resulting access
token. A hosted-login callback and browser CORS policy can be configured once the
frontend origin is known. No dashboard changes were needed for this deployment.
