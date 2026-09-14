"""Read-only deployment checks; no user passwords, tokens or product writes."""

import argparse
import json
from pathlib import Path
import urllib.error
import urllib.request

import boto3
from botocore.config import Config


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--region", default="us-west-2")
    parser.add_argument("--environment", default="dev")
    args = parser.parse_args()
    session = boto3.Session(region_name=args.region)
    config = Config(retries={"mode": "standard", "total_max_attempts": 3})
    cfn = session.client("cloudformation", config=config)
    outputs = {}
    checks = []
    for component in ["foundation", "backend"]:
        stack = cfn.describe_stacks(StackName=f"imhungry-{args.environment}-{component}")["Stacks"][0]
        assert stack["StackStatus"] in {"CREATE_COMPLETE", "UPDATE_COMPLETE"}, stack["StackStatus"]
        outputs.update({item["OutputKey"]: item["OutputValue"] for item in stack["Outputs"]})
        checks.append(component + " stack complete")
    function = session.client("lambda", config=config).get_function_configuration(FunctionName=outputs["FunctionName"])
    assert function["State"] == "Active" and function["LastUpdateStatus"] == "Successful"
    checks.append("Lambda active")
    with urllib.request.urlopen(outputs["ApiUrl"] + "/health", timeout=60) as response:
        assert response.status == 200
        assert json.loads(response.read()) == {"status": "ok"}
    checks.append("Public health returns 200")
    for headers in [{}, {"Authorization": "Bearer invalid-deployment-probe"}]:
        request = urllib.request.Request(outputs["ApiUrl"] + "/v1/profile", headers=headers)
        try:
            urllib.request.urlopen(request, timeout=30)
        except urllib.error.HTTPError as error:
            assert error.code in {401, 403}, error.code
        else:
            raise AssertionError("Gateway accepted an unauthenticated request")
    checks.append("Gateway rejects missing and invalid access tokens")
    with urllib.request.urlopen(outputs["Issuer"] + "/.well-known/jwks.json", timeout=30) as response:
        assert json.loads(response.read())["keys"]
    checks.append("Cognito signing keys published")
    table = session.client("dynamodb", config=config).describe_table(TableName=outputs["TableName"])["Table"]
    assert table["TableStatus"] == "ACTIVE" and table["GlobalSecondaryIndexes"][0]["IndexStatus"] == "ACTIVE"
    assert table["DeletionProtectionEnabled"]
    checks.append("DynamoDB table and GSI1 active with deletion protection")
    s3 = session.client("s3", config=config)
    assert all(s3.get_public_access_block(Bucket=outputs["BucketName"])["PublicAccessBlockConfiguration"].values())
    assert s3.get_bucket_encryption(Bucket=outputs["BucketName"])["ServerSideEncryptionConfiguration"]["Rules"]
    checks.append("S3 encryption and all public-access blocks enabled")
    iam = session.client("iam", config=config)
    account = outputs["ExecutionRoleArn"].split(":")[4]
    cases = [
        ("dynamodb:GetItem", table["TableArn"]),
        ("dynamodb:PutItem", table["TableArn"]),
        ("dynamodb:Query", table["TableArn"] + "/index/GSI1"),
        ("s3:GetObject", f"arn:aws:s3:::{outputs['BucketName']}/imhungry/{args.environment}/session/probe"),
        ("s3:PutObject", f"arn:aws:s3:::{outputs['BucketName']}/imhungry/{args.environment}/session/probe"),
        ("bedrock:InvokeModelWithResponseStream", f"arn:aws:bedrock:{args.region}:{account}:inference-profile/global.amazon.nova-2-lite-v1:0"),
        ("bedrock:InvokeModelWithResponseStream", "arn:aws:bedrock:::foundation-model/amazon.nova-2-lite-v1:0"),
    ]
    for action, resource in cases:
        results = iam.simulate_principal_policy(PolicySourceArn=outputs["ExecutionRoleArn"],
                                               ActionNames=[action], ResourceArns=[resource])["EvaluationResults"]
        assert all(item["EvalDecision"] == "allowed" for item in results), (action, resource, results)
    denied = iam.simulate_principal_policy(PolicySourceArn=outputs["ExecutionRoleArn"], ActionNames=["s3:GetObject"],
                                           ResourceArns=[f"arn:aws:s3:::{outputs['BucketName']}/artifacts/backend/probe.zip"])
    assert denied["EvaluationResults"][0]["EvalDecision"] == "implicitDeny"
    checks.append("IAM simulation allows runtime operations and denies deployment artifact access")
    report = {"region": args.region, "environment": args.environment, "outputs": outputs, "checks": checks,
              "limits": ["No authenticated user session exercised; these checks do not prove a full conversation round trip.",
                         "IAM simulation is not an end-to-end runtime test."]}
    target = Path(__file__).resolve().parents[1] / ".build/verification.json"
    target.parent.mkdir(exist_ok=True)
    target.write_text(json.dumps(report, indent=2) + "\n")
    print(json.dumps(report, indent=2))


if __name__ == "__main__":
    main()
