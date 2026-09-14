"""Prepare a reviewable change set; execute only the named, reviewed change set."""

import argparse
import hashlib
import json
from pathlib import Path
import time

import boto3
from botocore.config import Config
from botocore.exceptions import ClientError

ROOT = Path(__file__).resolve().parents[1]


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("component", choices=["foundation", "backend"])
    parser.add_argument("--region", default="us-west-2")
    parser.add_argument("--environment", default="dev")
    parser.add_argument("--execute", metavar="CHANGE_SET", help="Execute a previously reviewed change set")
    args = parser.parse_args()
    session = boto3.Session(region_name=args.region)
    config = Config(retries={"mode": "standard", "total_max_attempts": 3})
    cfn = session.client("cloudformation", config=config)
    stack = f"imhungry-{args.environment}-{args.component}"
    if args.execute:
        change_set = cfn.describe_change_set(StackName=stack, ChangeSetName=args.execute)
        changes = change_set.get("Changes", [])
        for change in changes:
            item = change["ResourceChange"]
            if item["Action"] not in {"Add", "Modify"} or item.get("Replacement") in {"True", "Conditional"}:
                raise RuntimeError(f"Destructive change requires manual review: {item}")
        if not changes or change_set["ExecutionStatus"] != "AVAILABLE":
            raise RuntimeError("The change set has no executable changes")
        cfn.execute_change_set(StackName=stack, ChangeSetName=args.execute)
        print(f"Started {stack}. Inspect stack status and outputs before using the app.")
        return

    template = json.loads((ROOT / "infra" / f"{args.component}.json").read_text())
    parameters = {"Environment": args.environment}
    if args.component == "backend":
        foundation = cfn.describe_stacks(StackName=f"imhungry-{args.environment}-foundation")["Stacks"][0]
        if foundation["StackStatus"] not in {"CREATE_COMPLETE", "UPDATE_COMPLETE"}:
            raise RuntimeError("The foundation stack must complete before backend deployment")
        outputs = {item["OutputKey"]: item["OutputValue"] for item in foundation["Outputs"]}
        parameters.update({name: outputs[name] for name in ["TableName", "BucketName", "UserPoolArn", "ClientId", "Issuer"]})
        archive = ROOT / ".build/backend.zip"
        key = "artifacts/backend/" + hashlib.sha256(archive.read_bytes()).hexdigest() + ".zip"
        session.client("s3", config=config).upload_file(str(archive), outputs["BucketName"], key,
                                                       ExtraArgs={"ServerSideEncryption": "AES256"})
        parameters["ArtifactKey"] = key
        # API Gateway deployments are immutable snapshots. Replace this resource
        # when API configuration changes, so updates reach the live stage.
        api_config = {key: value for key, value in template["Resources"].items()
                      if value["Type"].startswith("AWS::ApiGateway::") and key not in {"Stage", "Deployment"}}
        revision = hashlib.sha256(json.dumps(api_config, sort_keys=True).encode()).hexdigest()[:12]
        deployment = "Deployment" + revision
        template["Resources"][deployment] = template["Resources"].pop("Deployment")
        template["Resources"]["Stage"]["Properties"]["DeploymentId"] = {"Ref": deployment}
    kind = "UPDATE"
    try:
        existing = cfn.describe_stacks(StackName=stack)["Stacks"][0]
        if existing["StackStatus"] == "REVIEW_IN_PROGRESS":
            kind = "CREATE"
    except ClientError as error:
        if error.response["Error"]["Code"] == "ValidationError" and "does not exist" in error.response["Error"]["Message"]:
            kind = "CREATE"
        else:
            raise
    name = f"app-{int(time.time())}"
    cfn.create_change_set(StackName=stack, ChangeSetName=name, ChangeSetType=kind,
                          TemplateBody=json.dumps(template), Capabilities=["CAPABILITY_IAM"],
                          Parameters=[{"ParameterKey": key, "ParameterValue": value} for key, value in parameters.items()],
                          Tags=[{"Key": "App", "Value": "ImHungry"}, {"Key": "Environment", "Value": args.environment}])
    print(f"Preparing {stack} change set {name}", flush=True)
    cfn.get_waiter("change_set_create_complete").wait(StackName=stack, ChangeSetName=name,
                                                      WaiterConfig={"Delay": 5, "MaxAttempts": 60})
    result = cfn.describe_change_set(StackName=stack, ChangeSetName=name)
    for change in result.get("Changes", []):
        item = change["ResourceChange"]
        print(item["Action"], item["LogicalResourceId"], item["ResourceType"], item.get("Replacement", ""))
    print(f"Review complete: execute with --execute {name}")


if __name__ == "__main__":
    main()
