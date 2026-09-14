"""Production composition. No provisioning or import-time AWS access."""

import os
import re

import boto3
from botocore.config import Config
from strands.storage import S3Storage

from agent import create_dietitian_agent, _configured_model, DEFAULT_REGION
from .api import create_app
from .auth import CognitoVerifier
from .conversations import ConversationService
from .providers import BedrockNutritionProvider
from .repository import DynamoRepository
from .services import NutritionService


def app_factory():
    required = ["IMHUNGRY_TABLE", "IMHUNGRY_BUCKET", "COGNITO_ISSUER", "COGNITO_CLIENT_ID"]
    if any(not os.getenv(key) for key in required):
        raise RuntimeError("Configure IMHUNGRY_TABLE, IMHUNGRY_BUCKET, COGNITO_ISSUER and COGNITO_CLIENT_ID before starting the production API")
    environment = os.getenv("IMHUNGRY_ENV", "dev")
    if not re.fullmatch(r"[a-z0-9-]{1,40}", environment):
        raise RuntimeError("IMHUNGRY_ENV must contain lowercase letters, digits or hyphens")
    region = os.getenv("AWS_REGION", DEFAULT_REGION)
    config = Config(retries={"total_max_attempts": 3, "mode": "standard"}, connect_timeout=5, read_timeout=30)
    session = boto3.Session(region_name=region)
    repository = DynamoRepository(session.client("dynamodb", config=config), os.environ["IMHUNGRY_TABLE"])
    storage = S3Storage(os.environ["IMHUNGRY_BUCKET"], prefix=f"imhungry/{environment}", boto_session=session, boto_client_config=config)
    services = NutritionService(repository, provider=BedrockNutritionProvider(_configured_model))
    conversations = ConversationService(services, storage, create_dietitian_agent)
    return create_app(services, verifier=CognitoVerifier(os.environ["COGNITO_ISSUER"], os.environ["COGNITO_CLIENT_ID"]), conversations=conversations)
