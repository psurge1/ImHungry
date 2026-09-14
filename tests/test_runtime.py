import boto3
import pytest
from fastapi.testclient import TestClient
from moto import mock_aws

from imhungry import runtime


def test_production_startup_requires_configuration_before_aws(monkeypatch):
    for key in ("IMHUNGRY_TABLE", "IMHUNGRY_BUCKET", "COGNITO_ISSUER", "COGNITO_CLIENT_ID"):
        monkeypatch.delenv(key, raising=False)
    monkeypatch.setattr(runtime.boto3, "Session", lambda **kwargs: pytest.fail("Unexpected AWS client initialization"))
    with pytest.raises(RuntimeError, match="Configure"):
        runtime.app_factory()


def test_production_wiring_does_not_provision_resources(monkeypatch):
    with mock_aws():
        for key, value in {"IMHUNGRY_TABLE": "nutrition", "IMHUNGRY_BUCKET": "snapshots", "IMHUNGRY_ENV": "test",
                           "AWS_REGION": "us-east-1", "COGNITO_ISSUER": "https://cognito-idp.us-east-1.amazonaws.com/us-east-1_example", "COGNITO_CLIENT_ID": "client"}.items():
            monkeypatch.setenv(key, value)
        app = runtime.app_factory()
        assert TestClient(app).get("/health").json() == {"status": "ok"}
        assert boto3.client("dynamodb", region_name="us-east-1").list_tables()["TableNames"] == []
        assert boto3.client("s3", region_name="us-east-1").list_buckets()["Buckets"] == []
