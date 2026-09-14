"""Build and publish frontend/ to the CloudFormation-managed Amplify app."""

import argparse
import io
from pathlib import Path
import subprocess
import urllib.request
import zipfile

import boto3
from botocore.config import Config


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--region", default="us-west-2")
    parser.add_argument("--environment", default="dev")
    args = parser.parse_args()
    root = Path(__file__).resolve().parents[1]
    subprocess.run(["npm", "run", "build"], cwd=root / "frontend", check=True)
    session = boto3.Session(region_name=args.region)
    config = Config(retries={"mode": "standard", "total_max_attempts": 3})
    stack = session.client("cloudformation", config=config).describe_stacks(StackName=f"imhungry-{args.environment}-frontend")["Stacks"][0]
    if stack["StackStatus"] not in {"CREATE_COMPLETE", "UPDATE_COMPLETE"}:
        raise RuntimeError("Frontend infrastructure must complete first")
    outputs = {o["OutputKey"]: o["OutputValue"] for o in stack["Outputs"]}
    archive = io.BytesIO()
    with zipfile.ZipFile(archive, "w", zipfile.ZIP_DEFLATED) as bundle:
        for path in sorted((root / "frontend/dist").rglob("*")):
            if path.is_file():
                bundle.write(path, path.relative_to(root / "frontend/dist"))
    amplify = session.client("amplify", config=config)
    deployment = amplify.create_deployment(appId=outputs["AppId"], branchName="main")
    # The presigned upload URL stays in memory and is never logged or persisted.
    request = urllib.request.Request(deployment["zipUploadUrl"], data=archive.getvalue(), method="PUT", headers={"Content-Type": "application/zip"})
    try:
        with urllib.request.urlopen(request, timeout=120) as response:
            if response.status != 200:
                raise RuntimeError("Frontend upload did not succeed")
    except Exception:
        raise RuntimeError("Frontend upload failed; create a new deployment to retry") from None
    result = amplify.start_deployment(appId=outputs["AppId"], branchName="main", jobId=deployment["jobId"])
    print(f"Started Amplify job {result['jobSummary']['jobId']} for app {outputs['AppId']}")
    print(outputs["FrontendOrigin"])


if __name__ == "__main__":
    main()
